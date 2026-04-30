from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from mwgc import core
from mwgc.config import Config, load_config
from mwgc.errors import AuthError, ConfigError, MwgcError
from mwgc.models import ConversionResult
from mwgc.prompter import Prompter
from mwgc.uploader import UploadOutcome


class ConfigPrompter:
    """Prompter that pulls credentials from a Config and defers MFA to a callback."""

    def __init__(self, config: Config, mfa_callback):
        self._config = config
        self._mfa_callback = mfa_callback

    def email(self) -> str:
        return self._config.garmin_email

    def password(self) -> str:
        return self._config.garmin_password

    def mfa(self) -> str:
        return self._mfa_callback()


class App:
    """Single-window mwgc-gui."""

    def __init__(self, root: ctk.CTk | None = None):
        self.root = root or ctk.CTk()
        self.root.title("mwgc — MyWhoosh to Garmin Connect")
        self.root.geometry("720x520")

        self._mfa_response: queue.Queue[str | None] = queue.Queue()
        self._build_widgets()

    def _build_widgets(self) -> None:
        pad = {"padx": 12, "pady": 6}

        ctk.CTkLabel(self.root, text="GPX file:").grid(row=0, column=0, sticky="w", **pad)
        self.gpx_entry = ctk.CTkEntry(self.root, width=440)
        self.gpx_entry.grid(row=0, column=1, sticky="ew", **pad)
        ctk.CTkButton(
            self.root, text="Browse…", width=80, command=self._browse_gpx
        ).grid(row=0, column=2, **pad)

        ctk.CTkLabel(self.root, text="Output FIT:").grid(row=1, column=0, sticky="w", **pad)
        self.fit_entry = ctk.CTkEntry(
            self.root,
            width=440,
            placeholder_text="(default: input path with .fit extension)",
        )
        self.fit_entry.grid(row=1, column=1, sticky="ew", **pad)
        ctk.CTkButton(
            self.root, text="Browse…", width=80, command=self._browse_fit
        ).grid(row=1, column=2, **pad)

        self.skip_upload_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.root,
            text="Skip upload (write FIT only)",
            variable=self.skip_upload_var,
        ).grid(row=2, column=1, sticky="w", **pad)

        self.run_button = ctk.CTkButton(
            self.root, text="Run", command=self._on_run, width=120
        )
        self.run_button.grid(row=3, column=1, sticky="e", **pad)

        self.progress = ctk.CTkProgressBar(self.root)
        self.progress.set(0.0)
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)

        self.log = ctk.CTkTextbox(self.root, height=240)
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew", **pad)

        self.root.grid_rowconfigure(5, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

    def run(self) -> None:
        self.root.mainloop()

    # ---- user actions ----

    def _browse_gpx(self) -> None:
        path = filedialog.askopenfilename(
            title="Select GPX file",
            filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")],
        )
        if path:
            self.gpx_entry.delete(0, tk.END)
            self.gpx_entry.insert(0, path)

    def _browse_fit(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save FIT as",
            defaultextension=".fit",
            filetypes=[("FIT files", "*.fit"), ("All files", "*.*")],
        )
        if path:
            self.fit_entry.delete(0, tk.END)
            self.fit_entry.insert(0, path)

    def _on_run(self) -> None:
        gpx = self.gpx_entry.get().strip()
        if not gpx:
            messagebox.showerror("mwgc", "Please select a GPX file.")
            return

        fit = self.fit_entry.get().strip() or None
        skip_upload = self.skip_upload_var.get()

        config: Config | None = None
        if not skip_upload:
            try:
                config = load_config()
            except ConfigError as e:
                messagebox.showerror("mwgc — config error", str(e))
                return

        self._set_running(True)
        self.progress.set(0.0)
        self.log.delete("1.0", tk.END)
        self._log_line(f"Starting: {gpx}")

        worker = threading.Thread(
            target=self._run_worker,
            args=(gpx, fit, skip_upload, config),
            daemon=True,
        )
        worker.start()

    # ---- worker ----

    def _run_worker(
        self,
        gpx: str,
        fit: str | None,
        skip_upload: bool,
        config: Config | None,
    ) -> None:
        prompter: Prompter | None = None
        if config is not None:
            prompter = ConfigPrompter(config, mfa_callback=self._request_mfa_blocking)

        try:
            result, outcome = core.run(
                gpx,
                fit_path=fit,
                do_upload=not skip_upload,
                on_progress=self._post_progress,
                prompter=prompter,
            )
        except MwgcError as e:
            self.root.after(0, self._on_error, e)
            return
        except Exception as e:  # noqa: BLE001 -- final safety net for the worker
            self.root.after(0, self._on_error, e)
            return

        self.root.after(0, self._on_finished, result, outcome)

    def _post_progress(self, stage: str, fraction: float) -> None:
        # Called from the worker thread; bounce to UI thread before touching widgets.
        self.root.after(0, self._update_progress, stage, fraction)

    # ---- MFA bridge ----

    def _request_mfa_blocking(self) -> str:
        """Worker-thread side: ask the UI for an MFA code and block until it arrives."""
        while not self._mfa_response.empty():
            self._mfa_response.get_nowait()
        self.root.after(0, self._show_mfa_dialog)
        code = self._mfa_response.get()
        if code is None:
            raise AuthError("MFA cancelled by user")
        return code

    def _show_mfa_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Garmin Connect MFA")
        dialog.geometry("320x150")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="Enter the MFA code from your Garmin app:"
        ).pack(padx=16, pady=(16, 6))
        entry = ctk.CTkEntry(dialog, width=200)
        entry.pack(padx=16, pady=4)
        entry.focus_set()

        def submit():
            self._mfa_response.put(entry.get().strip())
            dialog.destroy()

        def cancel():
            self._mfa_response.put(None)
            dialog.destroy()

        button_row = ctk.CTkFrame(dialog, fg_color="transparent")
        button_row.pack(pady=10)
        ctk.CTkButton(button_row, text="OK", width=80, command=submit).pack(side="left", padx=6)
        ctk.CTkButton(button_row, text="Cancel", width=80, command=cancel).pack(side="left", padx=6)
        entry.bind("<Return>", lambda _e: submit())
        dialog.protocol("WM_DELETE_WINDOW", cancel)

    # ---- UI updates (must run on the UI thread) ----

    def _update_progress(self, stage: str, fraction: float) -> None:
        clamped = max(0.0, min(1.0, fraction))
        self.progress.set(clamped)
        pct = int(round(clamped * 100))
        self._log_line(f"[{pct:3d}%] {stage}")

    def _on_finished(
        self,
        result: ConversionResult,
        outcome: UploadOutcome | None,
    ) -> None:
        if outcome is None:
            tail = "Upload skipped."
        elif outcome == UploadOutcome.UPLOADED:
            tail = "Uploaded to Garmin Connect."
        else:
            tail = "Already on Garmin Connect (duplicate)."
        self._log_line(
            f"Done: {result.fit_path} ({result.point_count} points, "
            f"{result.duration_s:.1f}s, {result.distance_m:.1f} m). {tail}"
        )
        self._set_running(False)

    def _on_error(self, exc: BaseException) -> None:
        self._log_line(f"error: {exc}")
        messagebox.showerror("mwgc — error", str(exc))
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        self.gpx_entry.configure(state=state)
        self.fit_entry.configure(state=state)

    def _log_line(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)


def main() -> int:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    App().run()
    return 0
