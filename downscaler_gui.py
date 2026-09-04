import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from PIL import Image, UnidentifiedImageError

VALID_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
SUFFIX_RE = None
SUPPORTED_TARGETS = (256, 128, 64)


def is_image(path: Path) -> bool:
    return path.suffix.lower() in VALID_EXT


def has_downscale_suffix(path: Path) -> bool:
    global SUFFIX_RE
    if SUFFIX_RE is None:
        import re

        SUFFIX_RE = re.compile(r"_(\d+)$")
    m = SUFFIX_RE.search(path.stem)
    if not m:
        return False
    try:
        return int(m.group(1)) in SUPPORTED_TARGETS
    except ValueError:
        return False


def resolve_sources(paths):
    out = []
    seen = set()
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        if p.is_file():
            if is_image(p) and not has_downscale_suffix(p):
                if p.resolve() not in seen:
                    seen.add(p.resolve())
                    out.append(p)
        elif p.is_dir():
            for root, _dirs, files in os.walk(p):
                for f in files:
                    fpath = Path(root) / f
                    if is_image(fpath) and not has_downscale_suffix(fpath):
                        if fpath.resolve() not in seen:
                            seen.add(fpath.resolve())
                            out.append(fpath)
    return sorted(out)


def mirror_output_path(src: Path, source_root: Path, target: int) -> Path:
    src = src.resolve()
    source_root = source_root.resolve()
    try:
        rel = src.relative_to(source_root)
    except ValueError:
        rel = Path(src.name)
    out_dir = source_root / "_downscaled" / rel.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{src.stem}_{target}{src.suffix}"


def source_root_for(src: Path) -> Path:
    return src.parent if src.is_file() else src


def process_image(src: Path, targets, log_q: queue.Queue, stop_evt: threading.Event):
    try:
        with Image.open(src) as im:
            im.load()
            w, h = im.size
            mode = im.mode
    except (UnidentifiedImageError, OSError) as e:
        log_q.put(("ERR", src, f"illisible: {e}"))
        return

    if w != h:
        log_q.put(("ERR", src, f"non-carrée ({w}x{h}) skip"))
        return

    root = source_root_for(src)
    for t in targets:
        if stop_evt.is_set():
            return
        if w == t:
            log_q.put(("SKIP", src, f"déjà en {t}x{t}"))
            continue
        try:
            with Image.open(src) as im:
                im.load()
                out = im.resize((t, t), Image.Resampling.NEAREST)
                dst = mirror_output_path(src, root, t)
                save_kwargs = {}
                if dst.suffix.lower() in (".jpg", ".jpeg"):
                    if out.mode in ("RGBA", "P"):
                        out = out.convert("RGB")
                    save_kwargs["quality"] = 95
                out.save(dst, **save_kwargs)
            factor = w // t
            log_q.put(("OK", src, f"{w}x{w} -> {t}x{t} (x{factor})  [{dst.name}]"))
        except Exception as e:
            log_q.put(("ERR", src, f"échec {t}px: {e}"))


def worker(paths, targets, log_q, progress_q, done_evt, stop_evt):
    total = len(paths)
    progress_q.put(("init", total))
    ok = err = skip = 0
    for i, p in enumerate(paths, 1):
        if stop_evt.is_set():
            break
        before = log_q.qsize()
        process_image(p, targets, log_q, stop_evt)
        after = log_q.qsize()
        for _ in range(after - before):
            try:
                kind, src, msg = log_q.get_nowait()
            except queue.Empty:
                break
            if kind == "OK":
                ok += 1
            elif kind == "ERR":
                err += 1
            else:
                skip += 1
            log_q.put((kind, src, msg))
        progress_q.put(("step", i, total))
    done_evt.set()
    log_q.put(("__DONE__", None, f"Terminé : {ok} OK, {err} erreurs, {skip} skips, total {total}"))


class DownscalerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Downscaler PSX")
        self.geometry("780x560")
        self.minsize(680, 480)

        self.log_q = queue.Queue()
        self.progress_q = queue.Queue()
        self.worker_thread = None
        self.stop_evt = threading.Event()
        self.done_evt = threading.Event()
        self.running = False

        self._build_ui()
        self._poll_queues()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        top = ttk.LabelFrame(self, text="Source(s)")
        top.pack(fill="x", **pad)

        self.source_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.source_var).pack(
            side="left", fill="x", expand=True, padx=6, pady=6
        )
        ttk.Button(top, text="Parcourir fichiers…", command=self.browse_files).pack(
            side="left", padx=2, pady=6
        )
        ttk.Button(top, text="Parcourir dossier…", command=self.browse_folder).pack(
            side="left", padx=2, pady=6
        )

        tg = ttk.LabelFrame(self, text="Cibles (résolutions PSX)")
        tg.pack(fill="x", **pad)
        self.target_vars = {}
        for t in SUPPORTED_TARGETS:
            v = tk.BooleanVar(value=(t == 128))
            cb = ttk.Checkbutton(
                tg, text=f"{t}x{t}", variable=v, command=self._sync_launch_state
            )
            cb.pack(side="left", padx=10, pady=6)
            self.target_vars[t] = v

        out = ttk.LabelFrame(self, text="Sortie")
        out.pack(fill="x", **pad)
        ttk.Label(
            out,
            text="Dossier : _downscaled/ créé en miroir de l'arborescence d'entrée.",
        ).pack(side="left", padx=6, pady=6)
        ttk.Button(out, text="Ouvrir le dernier dossier de sortie", command=self.open_last_out).pack(
            side="right", padx=6, pady=6
        )

        ctl = ttk.Frame(self)
        ctl.pack(fill="x", **pad)
        self.launch_btn = ttk.Button(ctl, text="▶ Lancer", command=self.on_launch)
        self.launch_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(ctl, text="■ Stop", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(ctl, text="Effacer log", command=self.clear_log).pack(side="left", padx=4)
        ttk.Button(ctl, text="Ouvrir dossier de sortie (sélection)", command=self.open_output_dir).pack(
            side="right", padx=4
        )

        pf = ttk.Frame(self)
        pf.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(pf, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x", padx=4, pady=2)
        self.status_var = tk.StringVar(value="En attente.")
        ttk.Label(pf, textvariable=self.status_var).pack(anchor="w", padx=4)

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(logf, height=14, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        self._sync_launch_state()

    def _selected_targets(self):
        return sorted(t for t, v in self.target_vars.items() if v.get())

    def _sync_launch_state(self):
        has_src = bool(self.source_var.get().strip())
        has_tgt = bool(self._selected_targets())
        state = "normal" if (has_src and has_tgt and not self.running) else "disabled"
        self.launch_btn.configure(state=state)

    def browse_files(self):
        paths = filedialog.askopenfilenames(
            title="Sélectionner des textures",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"), ("Tous", "*.*")],
        )
        if not paths:
            return
        cur = self.source_var.get().strip()
        merged = cur + (";" if cur else "") + ";".join(paths) if cur else ";".join(paths)
        self.source_var.set(merged)
        self._sync_launch_state()

    def browse_folder(self):
        d = filedialog.askdirectory(title="Sélectionner un dossier (récursif)")
        if not d:
            return
        cur = self.source_var.get().strip()
        merged = cur + (";" if cur else "") + d if cur else d
        self.source_var.set(merged)
        self._sync_launch_state()

    def _append_log(self, line, tag=None):
        self.log.configure(state="normal")
        if tag:
            self.log.insert("end", line + "\n", tag)
        else:
            self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def open_last_out(self):
        paths = self._parse_sources()
        if not paths:
            messagebox.showinfo("Info", "Aucune source sélectionnée.")
            return
        last = paths[0]
        out_dir = source_root_for(last) / "_downscaled"
        if not out_dir.exists():
            messagebox.showinfo("Info", f"Dossier inexistant :\n{out_dir}")
            return
        try:
            os.startfile(str(out_dir))
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def open_output_dir(self):
        paths = self._parse_sources()
        if not paths:
            messagebox.showinfo("Info", "Aucune source sélectionnée.")
            return
        last = paths[-1]
        out_dir = source_root_for(last).parent / "_downscaled"
        if not out_dir.exists():
            messagebox.showinfo("Info", f"Dossier inexistant :\n{out_dir}")
            return
        try:
            os.startfile(str(out_dir))
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def _parse_sources(self):
        raw = self.source_var.get().strip()
        if not raw:
            return []
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        return [Path(p) for p in parts]

    def on_launch(self):
        if self.running:
            return
        sources = self._parse_sources()
        targets = self._selected_targets()
        if not sources:
            messagebox.showwarning("Manquant", "Sélectionnez au moins un fichier ou un dossier.")
            return
        if not targets:
            messagebox.showwarning("Manquant", "Cochez au moins une résolution cible.")
            return

        files = resolve_sources(sources)
        if not files:
            messagebox.showinfo("Vide", "Aucune image valide trouvée (carrée, format reconnu).")
            return

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.log.tag_configure("OK", foreground="#1f8a3a")
        self.log.tag_configure("ERR", foreground="#c0392b")
        self.log.tag_configure("SKIP", foreground="#9aa0a6")
        self.log.tag_configure("INFO", foreground="#1f5fa6")

        self._append_log(f"Démarrage : {len(files)} fichier(s), cibles={targets}", "INFO")

        self.running = True
        self.stop_evt.clear()
        self.done_evt.clear()
        self.launch_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.configure(mode="determinate", value=0, maximum=len(files))
        self.status_var.set(f"Traitement 0/{len(files)}…")

        self.worker_thread = threading.Thread(
            target=worker,
            args=(files, targets, self.log_q, self.progress_q, self.done_evt, self.stop_evt),
            daemon=True,
        )
        self.worker_thread.start()

    def on_stop(self):
        if not self.running:
            return
        self.stop_evt.set()
        self._append_log("Annulation demandée…", "INFO")

    def _poll_queues(self):
        try:
            while True:
                kind, src, msg = self.log_q.get_nowait()
                if kind == "__DONE__":
                    self._append_log(msg, "INFO")
                    self.status_var.set(msg)
                    self.running = False
                    self.stop_btn.configure(state="disabled")
                    self._sync_launch_state()
                    continue
                tag = kind
                if src is not None:
                    self._append_log(f"{kind:4s} {src.name}  {msg}", tag)
                else:
                    self._append_log(msg, tag)
        except queue.Empty:
            pass

        try:
            while True:
                ev = self.progress_q.get_nowait()
                if ev[0] == "init":
                    total = ev[1]
                    self.progress.configure(maximum=max(total, 1), value=0)
                    self.status_var.set(f"Traitement 0/{total}…")
                elif ev[0] == "step":
                    _t, i, total = ev
                    self.progress.configure(value=i, maximum=max(total, 1))
                    self.status_var.set(f"Traitement {i}/{total}…")
        except queue.Empty:
            pass

        self.after(80, self._poll_queues)


if __name__ == "__main__":
    DownscalerApp().mainloop()
