import os
import sys
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
import yt_dlp
import re
from PIL import Image, ImageTk

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'resources'))
    return os.path.join(base_path, relative_path)

def get_steam_path():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        return steam_path
    except Exception:
        return r"C:\Program Files (x86)\Steam"

def get_steam_libraries(steam_path):
    library_paths = [os.path.join(steam_path, "steamapps")]
    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if not os.path.isfile(vdf_path):
        return library_paths
    try:
        with open(vdf_path, encoding="utf-8") as f:
            text = f.read()
        matches = re.findall(r'"\d+"\s*"\s*([^"]+)\s*"', text)
        for path in matches:
            p = path.replace("\\\\", "\\")
            if os.path.isdir(p):
                library_paths.append(os.path.join(p, "steamapps"))
    except Exception:
        pass
    return library_paths

def find_msc_install_path():
    steam_path = get_steam_path()
    libraries = get_steam_libraries(steam_path)
    for lib in libraries:
        msc_dir = os.path.join(lib, "common", "My Summer Car")
        if os.path.isdir(msc_dir):
            return msc_dir
    return r"C:\Program Files (x86)\Steam\steamapps\common\My Summer Car"

DEFAULT_MSC_PATH = find_msc_install_path()

CD_SLOT_MAP = {
    "Radio": "Radio",
    "CD1": "CD1",
    "CD2": "CD2",
    "CD3": "CD3",
}

def is_youtube_playlist(url):
    return ("youtube.com/playlist" in url or "youtu.be/playlist" in url or
            ("youtube.com" in url and "list=" in url))

def is_soundcloud_playlist(url):
    return "soundcloud.com" in url and "sets" in url

def is_youtube_track(url):
    return ("youtu.be/" in url or "youtube.com/watch" in url) and not is_youtube_playlist(url)

def is_soundcloud_track(url):
    return "soundcloud.com" in url and not is_soundcloud_playlist(url)

def get_soundcloud_playlist_tracks(url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
        'forcejson': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if "entries" in info and info["entries"]:
            return [entry["url"] for entry in info["entries"] if "url" in entry]
    return []

def get_youtube_playlist_videos(playlist_url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
        'forcejson': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        if "entries" in info and info["entries"]:
            return [f"https://www.youtube.com/watch?v={entry['id']}" for entry in info["entries"]]
    return []

def get_single_track_info(url):
    return [url]

def download_track(url, out_path):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_path + '.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'forcejson': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'entries' in info:
                info = info['entries'][0]
            filepath = ydl.prepare_filename(info)
            thumbnail = info.get('thumbnail')
        return filepath, info.get('title') or os.path.basename(filepath), thumbnail
    except Exception:
        return None, None, None

def convert_track(filepath, idx, out_folder, high_quality=True, metadata=None):
    try:
        if not os.path.isfile(filepath):
            return False, f"Input file does not exist: {filepath}"
        ext = ".ogg"
        fname = f"track{idx}{ext}"
        out_path = os.path.join(out_folder, fname)
        if high_quality:
            audio_args = ['-ab', '320k']
        else:
            audio_args = ['-ab', '96k', '-ac', '2', '-ar', '22050']
        cmd = [
            FFMPEG_PATH,
            '-y',
            '-i', filepath,
        ]
        # Add metadata if provided
        if metadata:
            for k, v in metadata.items():
                if v:
                    cmd += ['-metadata', f'{k}={v}']
        cmd += [*audio_args, out_path]
        kwargs = {}
        if sys.platform == "win32":
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
        if proc.returncode != 0:
            return False, f"FFmpeg error: {proc.stderr.strip()}"
        if proc.returncode == 0 and os.path.getsize(filepath) < 500000:
            return False, "The song is region-locked and only a 30-second preview could be downloaded."
        os.remove(filepath)
        return True, out_path
    except Exception as e:
        return False, f"Conversion error: {str(e)}"

def get_next_track_number(folder):
    ext = ".ogg"
    files = [f for f in os.listdir(folder) if re.match(r'track(\d+)' + re.escape(ext), f)]
    numbers = [int(re.match(r'track(\d+)', f).group(1)) for f in files if re.match(r'track(\d+)', f)]
    return max(numbers, default=0) + 1

def confirm_and_clean_radio_folder(master, folder):
    existing_files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)) and f != "songnames.xml"]
    if existing_files:
        proceed = messagebox.askyesno(
            "Destination Folder Not Empty",
            "The folder is not empty. Do you want to DELETE ALL FILES in this folder and continue?"
        )
        if not proceed:
            return False
    for f in os.listdir(folder):
        if f == "songnames.xml":
            continue
        try:
            fp = os.path.join(folder, f)
            if os.path.isfile(fp):
                os.remove(fp)
        except Exception:
            pass
    return True

FFMPEG_PATH = resource_path(os.path.join('ffmpeg', 'bin', 'ffmpeg.exe')) \
    if sys.platform == "win32" else resource_path(os.path.join('ffmpeg', 'bin', 'ffmpeg'))

class MSCPlaylistGUI:
    def __init__(self, master):
        self.master = master
        self.cancel_flag = threading.Event()
        self.current_thread = None

        self.small_geometry = "410x175"
        master.title("MSC Playlist Converter")
        master.geometry(self.small_geometry)
        self.master.minsize(410, 175)
        self.master.resizable(False, False)

        main_frame = tk.Frame(master)
        main_frame.pack(expand=True, fill="both", padx=7, pady=7)

        row1 = tk.Frame(main_frame)
        row1.pack(anchor="center", pady=(4, 0))
        self.link_label = tk.Label(row1, text="Playlist/Track link:")
        self.link_label.pack(side="left", padx=(0, 3))
        self.entry = tk.Entry(row1, width=32, justify="center")
        self.entry.pack(side="left")
        tk.Button(row1, text="From Folder", command=self.convert_folder).pack(side="left", padx=(8, 0))

        mode_frame = tk.Frame(main_frame)
        mode_frame.pack(anchor="center", pady=(8, 2))
        self.output_mode_var = tk.StringVar(value="Radio")
        self.output_mode_menu = tk.OptionMenu(mode_frame, self.output_mode_var, "Radio", "CD1", "CD2", "CD3", command=lambda _: self.update_cd_controls())
        self.output_mode_menu.pack(side="left")
        self.cover_path_var = tk.StringVar(value="")
        self.coverart_btn = tk.Button(mode_frame, text="Import Coverart", command=self.import_coverart)
        self.coverart_btn.pack(side="left", padx=(8,0))
        self.coverart_thumbnail = tk.Label(mode_frame)
        self.coverart_thumbnail.pack(side="left", padx=(4,0))
        self.high_quality_var = tk.BooleanVar(value=False)
        self.high_quality_checkbox = tk.Checkbutton(mode_frame, text="High Quality", variable=self.high_quality_var)
        self.high_quality_checkbox.pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="Waiting")
        self.current_song_var = tk.StringVar(value="")
        self.status_song_var = tk.StringVar()
        self._current_index = None
        self._total = None
        self._current_title = None
        self._update_status_song_var()
        self.status_song_label = tk.Label(
            main_frame,
            textvariable=self.status_song_var,
            anchor="center",
            justify="center",
            font=("TkDefaultFont", 9)
        )
        self.status_song_label.pack(pady=(2, 0), fill="x")

        self.progress = ttk.Progressbar(main_frame, orient="horizontal", length=320, mode="determinate", maximum=100)
        self.progress.pack(pady=(2, 8))

        self.button_frame = tk.Frame(main_frame)
        self.button_frame.pack(pady=(0, 10))

        # Add tooltip for high-quality checkbox
        def show_high_quality_tooltip(event):
            x = self.high_quality_checkbox.winfo_rootx() + self.high_quality_checkbox.winfo_width() + 10
            y = self.high_quality_checkbox.winfo_rooty() + 8
            tooltip = tk.Toplevel(self.high_quality_checkbox)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                tooltip,
                text="High quality .ogg files take a long time to import in MSC!",
                justify='left',
                background="#ffffe0",
                relief='solid',
                borderwidth=1,
                font=("tahoma", "8", "normal")
            )
            label.pack(ipadx=1)
            self.high_quality_tooltip = tooltip

        def hide_high_quality_tooltip(event):
            if hasattr(self, 'high_quality_tooltip') and self.high_quality_tooltip:
                self.high_quality_tooltip.destroy()
                self.high_quality_tooltip = None

        self.high_quality_checkbox.bind("<Enter>", show_high_quality_tooltip)
        self.high_quality_checkbox.bind("<Leave>", hide_high_quality_tooltip)

        self.download_button = tk.Button(self.button_frame, text="Start", command=self.start_download)
        self.download_button.pack(side="left", padx=(0, 8))
        self.cancel_button = tk.Button(self.button_frame, text="Cancel", command=self.cancel_download, state='disabled')
        self.cancel_button.pack(side="left", padx=(0, 8))

        # Move the 'Output Folder' button to the same line as the Start and Cancel buttons, aligned to the right
        self.open_output_btn = tk.Button(self.button_frame, text="Output Folder", command=self.open_output_folder)
        self.open_output_btn.pack(side="right", padx=(8, 0))

        self.playlist = []
        self.thumbnail_path = None
        self.update_cd_controls()

    def update_cd_controls(self):
        is_cd = self.output_mode_var.get().startswith("CD")
        state = "normal" if is_cd else "disabled"
        self.coverart_btn.config(state=state)
        self.coverart_thumbnail.config(state=state)

    def show_output_folder_tooltip(self, event):
        path = self.get_output_folder()
        x = self.open_output_btn.winfo_rootx() + self.open_output_btn.winfo_width() + 10
        y = self.open_output_btn.winfo_rooty() + 8
        self.radio_folder_tooltip = tw = tk.Toplevel(self.open_output_btn)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=path,
            justify='left',
            background="#ffffe0",
            relief='solid',
            borderwidth=1,
            font=("tahoma", "8", "normal")
        )
        label.pack(ipadx=1)

    def hide_output_folder_tooltip(self, event):
        if self.radio_folder_tooltip:
            self.radio_folder_tooltip.destroy()
            self.radio_folder_tooltip = None

    def import_coverart(self):
        path = filedialog.askopenfilename(
            title="Select cover image (jpg/png)", filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.gif")])
        if not path:
            return
        self.cover_path_var.set(path)
        self.update_coverart_thumbnail(path)

    def update_coverart_thumbnail(self, path):
        try:
            img = Image.open(path)
            img.thumbnail((32,32))
            img_tk = ImageTk.PhotoImage(img)
            self.coverart_thumbnail.configure(image=img_tk)
            self.coverart_thumbnail.image = img_tk
        except Exception:
            self.coverart_thumbnail.configure(image="")

    def safe_after(self, func, *args, **kwargs):
        if self.cancel_flag.is_set():
            return
        self.master.after(0, lambda: func(*args, **kwargs))

    def set_progress(self, current, total):
        percent = int(current / total * 100)
        self.progress['value'] = percent

    def set_status(self, status):
        self.status_var.set(status)
        self._current_index = None
        self._total = None
        self._current_title = None
        self._update_status_song_var()

    def set_current_song(self, title, idx=None, total=None):
        self.current_song_var.set(f"Current: {title}")
        if idx is not None and total is not None:
            self._current_index = idx
            self._total = total
            self._current_title = title
        else:
            self._current_index = None
            self._total = None
            self._current_title = None
        self._update_status_song_var()

    def clear_current_song(self):
        self.current_song_var.set("")
        self._current_index = None
        self._total = None
        self._current_title = None
        self._update_status_song_var()

    def _update_status_song_var(self):
        if self._current_index is not None and self._total is not None and self._current_title:
            combined = f"Processing ({self._current_index}/{self._total}) | {self._current_title}"
        else:
            status = self.status_var.get()
            song = self.current_song_var.get()
            if song:
                combined = f"{status} | {song}"
            else:
                combined = status
        self.status_song_var.set(combined)

    def show_error(self, msg):
        self.set_status("Waiting")
        self.clear_current_song()
        messagebox.showerror("Error", msg)

    def show_success(self, files):
        self.progress['value'] = 100
        self.set_status("Finished")
        self.clear_current_song()
        messagebox.showinfo("Success", f"Processed {len(files)} song(s)!\nSaved to:\n{self.get_output_folder()}")

    def get_output_folder(self):
        val = self.output_mode_var.get()
        return os.path.join(DEFAULT_MSC_PATH, CD_SLOT_MAP[val])

    def open_output_folder(self):
        path = self.get_output_folder()
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def start_download(self):
        url = self.entry.get().strip()
        out_folder = self.get_output_folder()
        is_cd = self.output_mode_var.get().startswith("CD")

        urls_to_dl = []
        single_track = False
        if url:
            if is_youtube_track(url) or is_soundcloud_track(url):
                urls_to_dl = get_single_track_info(url)
                single_track = True
            elif is_soundcloud_playlist(url):
                urls_to_dl = get_soundcloud_playlist_tracks(url)
            elif is_youtube_playlist(url):
                urls_to_dl = get_youtube_playlist_videos(url)
            else:
                self.show_error("Invalid link. Please enter a SoundCloud/YouTube link.")
                return

        total = len(urls_to_dl)
        if total == 0:
            self.show_error("No songs to process. Please enter a link or use the From Folder button.")
            return

        if not os.path.isdir(out_folder):
            try:
                os.makedirs(out_folder)
            except Exception:
                self.show_error(f"Output folder not found and could not be created:\n{out_folder}")
                return

        # Only clean folder for playlists, not single tracks
        if not single_track:
            if not confirm_and_clean_radio_folder(self.master, out_folder):
                self.show_error("Aborted by user (output folder not cleaned).")
                return

        self.progress['value'] = 0
        self.set_status("Processing ...")
        self.clear_current_song()
        self.download_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.cancel_flag.clear()

        def task():
            files = []
            coverart_done = False
            coverart_path = self.cover_path_var.get()
            try:
                for idx, media_url in enumerate(urls_to_dl, 1):
                    if self.cancel_flag.is_set():
                        self.safe_after(self.set_status, "Cancelled")
                        self.safe_after(self.download_button.config, state='normal')
                        self.safe_after(self.cancel_button.config, state='disabled')
                        return
                    # For single track, use next available track number
                    if single_track:
                        track_idx = get_next_track_number(out_folder)
                        filepath, title, thumbnail = download_track(media_url, os.path.join(out_folder, f"track{track_idx}"))
                        # Try to extract metadata from info if available
                        info = None
                        try:
                            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                                info = ydl.extract_info(media_url, download=False)
                        except Exception:
                            pass
                        metadata = {}
                        if info:
                            metadata['title'] = info.get('title')
                            metadata['artist'] = info.get('artist') or info.get('uploader')
                            metadata['genre'] = info.get('genre')
                            # Length in seconds to mm:ss
                            duration = info.get('duration')
                            if duration:
                                minutes = int(duration // 60)
                                seconds = int(duration % 60)
                                metadata['comment'] = f"Length: {minutes}:{seconds:02d}"
                        else:
                            metadata['title'] = title
                        success, result = convert_track(filepath, track_idx, out_folder, self.high_quality_var.get(), metadata)
                    else:
                        track_idx = idx
                        filepath, title, thumbnail = download_track(media_url, os.path.join(out_folder, f"track{track_idx}"))
                        metadata = {'title': title}
                        success, result = convert_track(filepath, track_idx, out_folder, self.high_quality_var.get(), metadata)
                    if not filepath:
                        continue
                    self.safe_after(self.set_current_song, title or "Unknown", track_idx, total)
                    if not success:
                        self.safe_after(self.show_error, result)
                        continue
                    files.append(result)
                    if is_cd and not coverart_done and not coverart_path and thumbnail:
                        thumb_path = os.path.join(out_folder, "coverart.jpg")
                        try:
                            import urllib.request
                            urllib.request.urlretrieve(thumbnail, thumb_path)
                            self.safe_after(self.update_coverart_thumbnail, thumb_path)
                            coverart_path = thumb_path
                            coverart_done = True
                        except Exception:
                            pass
                    self.safe_after(self.set_progress, idx, total)

                if is_cd:
                    coverart_final = os.path.join(out_folder, "cd.png")
                    if coverart_path:
                        try:
                            img = Image.open(coverart_path)
                            img = img.resize((512,512))
                            img.save(coverart_final)
                            self.safe_after(self.update_coverart_thumbnail, coverart_final)
                        except Exception:
                            pass
                    else:
                        img = Image.new("RGB", (512,512), (30,30,30))
                        img.save(coverart_final)
                        self.safe_after(self.update_coverart_thumbnail, coverart_final)

                self.safe_after(self.clear_current_song)
                if self.cancel_flag.is_set():
                    self.safe_after(self.set_status, "Cancelled")
                elif files:
                    self.safe_after(self.show_success, files)
                else:
                    self.safe_after(self.show_error, "No songs processed.")
                self.safe_after(self.cancel_button.config, state='disabled')
            except Exception as e:
                self.safe_after(self.show_error, str(e))
                self.safe_after(self.set_status, "Waiting")
                self.safe_after(self.cancel_button.config, state='disabled')
            finally:
                self.safe_after(self.download_button.config, state='normal')

        self.current_thread = threading.Thread(target=task, daemon=True)
        self.current_thread.start()

    def convert_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing audio files")
        if not folder:
            return
        out_folder = self.get_output_folder()
        is_cd = self.output_mode_var.get().startswith("CD")

        files = []
        for fname in sorted(os.listdir(folder)):
            if fname.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a")):
                files.append(os.path.join(folder, fname))
        total = len(files)
        if total == 0:
            self.show_error("No supported audio files in selected folder.")
            return

        if not os.path.isdir(out_folder):
            try:
                os.makedirs(out_folder)
            except Exception:
                self.show_error(f"Output folder not found and could not be created:\n{out_folder}")
                return

        if not confirm_and_clean_radio_folder(self.master, out_folder):
            self.show_error("Aborted by user (output folder not cleaned).")
            return

        self.progress['value'] = 0
        self.set_status("Processing ...")
        self.clear_current_song()
        self.download_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.cancel_flag.clear()

        def task():
            processed_files = []
            coverart_path = self.cover_path_var.get()
            try:
                for idx, localfile in enumerate(files, 1):
                    if self.cancel_flag.is_set():
                        self.safe_after(self.set_status, "Cancelled")
                        self.safe_after(self.download_button.config, state='normal')
                        self.safe_after(self.cancel_button.config, state='disabled')
                        return
                    fname = os.path.basename(localfile)
                    self.safe_after(self.set_current_song, fname, idx, total)
                    success, result = convert_track(localfile, idx, out_folder, self.high_quality_var.get())
                    if not success:
                        self.safe_after(self.show_error, result)
                        continue
                    processed_files.append(result)
                    self.safe_after(self.set_progress, idx, total)
                if is_cd:
                    coverart_final = os.path.join(out_folder, "cd.png")
                    if coverart_path:
                        try:
                            img = Image.open(coverart_path)
                            img = img.resize((512,512))
                            img.save(coverart_final)
                            self.safe_after(self.update_coverart_thumbnail, coverart_final)
                        except Exception:
                            pass
                    else:
                        img = Image.new("RGB", (512,512), (30,30,30))
                        img.save(coverart_final)
                        self.safe_after(self.update_coverart_thumbnail, coverart_final)

                self.safe_after(self.clear_current_song)
                if self.cancel_flag.is_set():
                    self.safe_after(self.set_status, "Cancelled")
                elif processed_files:
                    self.safe_after(self.show_success, processed_files)
                else:
                    self.safe_after(self.show_error, "No songs processed.")
                self.safe_after(self.cancel_button.config, state='disabled')
            except Exception as e:
                self.safe_after(self.show_error, str(e))
                self.safe_after(self.set_status, "Waiting")
                self.safe_after(self.cancel_button.config, state='disabled')
            finally:
                self.safe_after(self.download_button.config, state='normal')

        self.current_thread = threading.Thread(target=task, daemon=True)
        self.current_thread.start()

    def cancel_download(self):
        self.cancel_flag.set()
        self.set_status("Cancelled")
        self.progress['value'] = 0
        self.status_song_var.set("Cancelled")
        self.cancel_button.config(state='disabled')
        self.download_button.config(state='normal')
        if self.current_thread and self.current_thread.is_alive():
            self.current_thread.join(timeout=1.0)
        self.current_thread = None

if __name__ == "__main__":
    for sub in ["Radio", "CD1", "CD2", "CD3"]:
        os.makedirs(os.path.join(DEFAULT_MSC_PATH, sub), exist_ok=True)
    root = tk.Tk()
    app = MSCPlaylistGUI(root)
    root.iconbitmap(resource_path('icon.ico'))
    root.mainloop()