from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from mwgc import core, history
from mwgc.cli import _find_latest_gpx
from mwgc.errors import AuthError, GpxParseError, MwgcError
from mwgc.gpx_parser import parse_gpx
from mwgc.models import ConversionResult
from mwgc.uploader import UploadOutcome


class _DialogPrompter:
    """Prompter that asks the UI thread for credentials via modal dialogs.

    Safe to call from the worker thread: each method blocks until the user
    submits or cancels.  Cancelling raises AuthError so the worker stops
    cleanly.
    """

    def __init__(self, request_fn):
        # request_fn(prompt, secret) -> str, raises AuthError on cancel
        self._request = request_fn

    def email(self) -> str:
        return self._request("Garmin Connect email:", secret=False)

    def password(self) -> str:
        return self._request("Garmin Connect password:", secret=True)

    def mfa(self) -> str:
        return self._request("MFA code from your authenticator app:", secret=False)


class App:
    """Single-window mwgc-gui."""

    def __init__(self, root: ctk.CTk | None = None):
        self.root = root or ctk.CTk()
        self.root.title("mwgc — MyWhoosh to Garmin Connect")
        self.root.geometry("720x520")

        self._credential_response: queue.Queue[str | None] = queue.Queue()
        self._build_widgets()

    def _build_widgets(self) -> None:
        pad = {"padx": 12, "pady": 6}

        # Row 0: GPX input.  In folder mode the label and Browse handler
        # change so the same row picks a directory instead of a file.
        self.gpx_label = ctk.CTkLabel(self.root, text="GPX file:")
        self.gpx_label.grid(row=0, column=0, sticky="w", **pad)
        self.gpx_entry = ctk.CTkEntry(self.root, width=440)
        self.gpx_entry.grid(row=0, column=1, sticky="ew", **pad)
        self.gpx_browse = ctk.CTkButton(
            self.root, text="Browse…", width=80, command=self._browse_gpx
        )
        self.gpx_browse.grid(row=0, column=2, **pad)

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

        # Row 2: option toggles in a single horizontal frame.
        toggles = ctk.CTkFrame(self.root, fg_color="transparent")
        toggles.grid(row=2, column=1, sticky="w", **pad)

        self.folder_mode_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            toggles,
            text="Folder mode (use latest .gpx in folder)",
            variable=self.folder_mode_var,
            command=self._on_folder_mode_toggled,
        ).pack(side="left", padx=(0, 16))

        self.skip_upload_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            toggles,
            text="Skip upload (write FIT only)",
            variable=self.skip_upload_var,
        ).pack(side="left")

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

    def _on_folder_mode_toggled(self) -> None:
        """Swap the input label/text between file mode and folder mode."""
        if self.folder_mode_var.get():
            self.gpx_label.configure(text="Folder:")
            self.gpx_entry.configure(placeholder_text="(folder containing .gpx exports)")
        else:
            self.gpx_label.configure(text="GPX file:")
            self.gpx_entry.configure(placeholder_text="")
        # Clear stale value so a path-from-the-other-mode doesn't linger.
        self.gpx_entry.delete(0, tk.END)

    def _browse_gpx(self) -> None:
        if self.folder_mode_var.get():
            path = filedialog.askdirectory(title="Select folder containing GPX files")
        else:
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
        raw = self.gpx_entry.get().strip()
        folder_mode = self.folder_mode_var.get()
        if not raw:
            messagebox.showerror(
                "mwgc",
                "Please select a folder." if folder_mode else "Please select a GPX file.",
            )
            return

        fit = self.fit_entry.get().strip() or None
        skip_upload = self.skip_upload_var.get()

        # Reset UI for this run before doing any blocking work.
        self.progress.set(0.0)
        self.log.delete("1.0", tk.END)

        # Folder mode: resolve the newest .gpx and short-circuit if it's
        # already in the local upload history (matches CLI --latest semantics).
        if folder_mode:
            try:
                gpx = str(_find_latest_gpx(Path(raw)))
            except GpxParseError as e:
                messagebox.showerror("mwgc — folder error", str(e))
                return
            self._log_line(f"Latest GPX in folder: {gpx}")
            if not skip_upload and self._already_uploaded(gpx):
                self._log_line("Already uploaded earlier — skipping.")
                return
        else:
            gpx = raw
            self._log_line(f"Starting: {gpx}")

        self._set_running(True)

        worker = threading.Thread(
            target=self._run_worker,
            args=(gpx, fit, skip_upload),
            daemon=True,
        )
        worker.start()

    def _already_uploaded(self, gpx_path: str) -> bool:
        """Best-effort history check; failures fall through to the normal upload."""
        try:
            _, start_time = parse_gpx(gpx_path)
        except GpxParseError:
            return False
        return history.was_uploaded(start_time)

    # ---- worker ----

    def _run_worker(self, gpx: str, fit: str | None, skip_upload: bool) -> None:
        prompter = _DialogPrompter(self._request_credential_blocking)

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

    # ---- credential / MFA bridge ----

    def _request_credential_blocking(self, prompt: str, secret: bool) -> str:
        """Worker-thread side: ask the UI for a value and block until it arrives."""
        while not self._credential_response.empty():
            self._credential_response.get_nowait()
        self.root.after(0, self._show_credential_dialog, prompt, secret)
        value = self._credential_response.get()
        if value is None:
            raise AuthError("Login cancelled by user")
        return value

    def _show_credential_dialog(self, prompt: str, secret: bool) -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Garmin Connect")
        dialog.geometry("360x160")
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=prompt).pack(padx=16, pady=(16, 6))
        entry = ctk.CTkEntry(dialog, width=240, show="*" if secret else "")
        entry.pack(padx=16, pady=4)
        entry.focus_set()

        def submit():
            self._credential_response.put(entry.get().strip())
            dialog.destroy()

        def cancel():
            self._credential_response.put(None)
            dialog.destroy()

        button_row = ctk.CTkFrame(dialog, fg_color="transparent")
        button_row.pack(pady=10)
        ctk.CTkButton(button_row, text="OK", width=80, command=submit).pack(
            side="left", padx=6
        )
        ctk.CTkButton(button_row, text="Cancel", width=80, command=cancel).pack(
            side="left", padx=6
        )
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
