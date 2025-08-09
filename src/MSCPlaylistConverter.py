import os
import sys
import threading
import subprocess
import time
import logging
import urllib.parse
import tempfile
import re
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
import yt_dlp
from PIL import Image

try:
    import winreg
except ImportError:
    winreg = None

# Application constants
APP_VERSION = "2.3"

# Audio encoding settings
HIGH_QUALITY_BITRATE = "320k"
HIGH_QUALITY_SAMPLE_RATE = "48000"
STANDARD_QUALITY_BITRATE = "96k"
STANDARD_QUALITY_SAMPLE_RATE = "22050"
STANDARD_QUALITY_CHANNELS = "2"

# Audio normalization parameters
NORMALIZATION_LOUDNESS = "-18"
NORMALIZATION_LRA = "11"
NORMALIZATION_TRUE_PEAK = "-1.5"

# yt-dlp configuration presets
BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
}

EXTRACT_OPTS = {
    **BASE_YDL_OPTS,
    'extract_flat': True,
    'skip_download': True,
    'forcejson': True,
}

DOWNLOAD_OPTS = {
    **BASE_YDL_OPTS,
    'format': 'bestaudio/best',
    'noplaylist': True,
    'forcejson': True,
}

SEARCH_OPTS = {
    **BASE_YDL_OPTS,
    'extract_flat': True,
}

# SoundCloud region-lock detection (preview track duration range in seconds)
REGION_LOCK_MIN_DURATION = 29
REGION_LOCK_MAX_DURATION = 31

# Centralized temporary directory path
APP_TEMP_DIR = os.path.join(tempfile.gettempdir(), 'MSC-Playlist-Converter')

def setup_logging():
    """Initialize logging system with timestamped log files."""
    log_dir = os.path.join(APP_TEMP_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f'msc_converter_{timestamp}.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"MSC Playlist Converter")
    logger.info(f"App Version: v{APP_VERSION}")
    logger.info("Application started")
    logger.info(f"Log file location: {log_file}")
    logger.info(f"App temp directory: {APP_TEMP_DIR}")
    return logger

logger = setup_logging()

def resource_path(relative_path):
    """Get absolute path to resource file."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'resources'))
    return os.path.join(base_path, relative_path)

def get_steam_path():
    """Retrieve Steam installation path from Windows registry."""
    if winreg is None:
        return r"C:\Program Files (x86)\Steam"
    
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        logger.info(f"Found Steam path in registry: {steam_path}")
        return steam_path
    except Exception as e:
        default_path = r"C:\Program Files (x86)\Steam"
        logger.warning(f"Registry lookup failed, using default: {default_path}")
        return default_path

def get_steam_libraries(steam_path):
    """Parse Steam library folders from libraryfolders.vdf file."""
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
    """Locate My Summer Car installation directory across Steam libraries."""
    steam_path = get_steam_path()
    libraries = get_steam_libraries(steam_path)
    logger.info(f"Searching for My Summer Car in {len(libraries)} Steam libraries")
    
    for lib in libraries:
        msc_dir = os.path.join(lib, "common", "My Summer Car")
        if os.path.isdir(msc_dir):
            logger.info(f"Found My Summer Car installation at: {msc_dir}")
            return msc_dir
    
    default_path = r"C:\Program Files (x86)\Steam\steamapps\common\My Summer Car"
    logger.warning(f"My Summer Car not found, using default path: {default_path}")
    return default_path

DEFAULT_MSC_PATH = find_msc_install_path()

CD_SLOT_MAP = {
    "Radio": "Radio",
    "CD1": "CD1",
    "CD2": "CD2",
    "CD3": "CD3",
}

def format_file_size_with_extension(filepath):
    """Format file size in human-readable format with extension for privacy logging."""
    try:
        size_bytes = os.path.getsize(filepath)
        if size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024):.1f}MB"
        elif size_bytes >= 1024:
            size_str = f"{size_bytes / 1024:.1f}KB"
        else:
            size_str = f"{size_bytes}B"
        _, ext = os.path.splitext(filepath)
        return f"{size_str}{ext}"
    except (OSError, TypeError):
        _, ext = os.path.splitext(filepath)
        return f"unknown_size{ext}"

def is_youtube_playlist(url):
    """Check if URL points to a YouTube playlist."""
    return ("youtube.com/playlist" in url or "youtu.be/playlist" in url or
            ("youtube.com" in url and "list=" in url))

def is_soundcloud_playlist(url):
    """Check if URL points to a SoundCloud playlist/set."""
    return "soundcloud.com" in url and "sets" in url

def is_youtube_track(url):
    """Check if URL points to a single YouTube video."""
    return ("youtu.be/" in url or "youtube.com/watch" in url) and not is_youtube_playlist(url)

def is_soundcloud_track(url):
    """Check if URL points to a single SoundCloud track."""
    return "soundcloud.com" in url and not is_soundcloud_playlist(url)

def get_soundcloud_playlist_tracks(url):
    """Extract track URLs from a SoundCloud playlist."""
    with yt_dlp.YoutubeDL(EXTRACT_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
        if "entries" in info and info["entries"]:
            return [entry["url"] for entry in info["entries"] if "url" in entry]
    return []

def get_youtube_playlist_videos(playlist_url):
    """Extract video URLs from a YouTube playlist."""
    with yt_dlp.YoutubeDL(EXTRACT_OPTS) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        if "entries" in info and info["entries"]:
            return [f"https://www.youtube.com/watch?v={entry['id']}" for entry in info["entries"]]
    return []

def get_single_track_info(url):
    """Wrap single track URL in list format for uniform processing."""
    return [url]

def download_track(url, out_path):
    """Download audio track with YouTube fallback for region-locked content."""
    try:
        logger.info(f"Starting download: {url}")
        
        download_temp_dir = os.path.join(APP_TEMP_DIR, 'downloads')
        os.makedirs(download_temp_dir, exist_ok=True)
        
        temp_download_path = os.path.join(download_temp_dir, os.path.basename(out_path))
        
        ydl_opts = {
            **DOWNLOAD_OPTS,
            'outtmpl': temp_download_path + '.%(ext)s',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'entries' in info:
                info = info['entries'][0]
            filepath = ydl.prepare_filename(info)
            thumbnail = info.get('thumbnail')
        
        title = info.get('title') or os.path.basename(filepath)
        
        # Detect region-locked SoundCloud previews by duration
        duration = info.get('duration')
        if duration and REGION_LOCK_MIN_DURATION < duration < REGION_LOCK_MAX_DURATION and "soundcloud.com" in url.lower():
            logger.warning(f"Region-locked preview detected (duration: {duration}s): {title}")
            
            # Attempt YouTube fallback for region-locked content
            logger.info(f"Attempting YouTube fallback for: {title}")
            youtube_url = search_youtube_fallback(title, info.get('uploader'))
            if youtube_url:
                logger.info(f"Found YouTube alternative: {youtube_url}")
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
                return download_track(youtube_url, out_path)
            else:
                logger.warning(f"No YouTube fallback found for: {title}")
                return None, None, None
        logger.info(f"Successfully downloaded: {title}")
        return filepath, title, thumbnail
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        return None, None, None

def search_youtube_fallback(title, artist=None):
    """Search YouTube for alternative version of region-locked track."""
    try:
        logger.info(f"Searching YouTube fallback for: {title} by {artist}")
        
        # Build search query variations for better match probability
        search_queries = []
        
        if artist:
            search_queries.extend([
                f"{artist} - {title}",
                f"{artist} {title}",
                f"{title} {artist}",
                f"{artist} {title} audio",
                f"{artist} {title} song"
            ])
        
        search_queries.extend([
            title,
            f"{title} audio",
            f"{title} song"
        ])
        
        with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
            for query in search_queries:
                try:
                    # Remove common suffixes that might interfere with search
                    clean_query = re.sub(r'\s*\(.*?\)\s*$', '', query)
                    clean_query = re.sub(r'\s*\[.*?\]\s*$', '', clean_query)
                    
                    logger.debug(f"Searching YouTube: {clean_query}")
                    search_url = f"ytsearch3:{clean_query}"
                    
                    search_results = ydl.extract_info(search_url, download=False)
                    
                    if search_results and 'entries' in search_results:
                        for entry in search_results['entries']:
                            if entry and 'id' in entry:
                                video_id = entry['id']
                                youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                                video_title = entry.get('title', 'Unknown')
                                logger.info(f"Found YouTube match: {video_title}")
                                return youtube_url
                    
                except Exception as e:
                    logger.debug(f"Search failed for '{query}': {e}")
                    continue
        
        logger.warning(f"No YouTube fallback found for: {title} by {artist}")
        return None
        
    except Exception as e:
        logger.error(f"YouTube fallback search failed: {e}")
        return None

def build_ffmpeg_command(filepath, out_path, high_quality, normalize_audio, metadata=None):
    """Construct FFmpeg command with quality and normalization settings."""
    if high_quality:
        audio_args = ['-ab', HIGH_QUALITY_BITRATE, '-ar', HIGH_QUALITY_SAMPLE_RATE]
    else:
        audio_args = ['-ab', STANDARD_QUALITY_BITRATE, '-ac', STANDARD_QUALITY_CHANNELS, '-ar', STANDARD_QUALITY_SAMPLE_RATE]
    
    cmd = [
        FFMPEG_PATH,
        '-y',
        '-i', filepath,
        '-vn',  # Skip video streams
        '-c:a', 'libvorbis',  # Force Vorbis codec
    ]
    
    if normalize_audio:
        cmd += ['-af', f'loudnorm=I={NORMALIZATION_LOUDNESS}:LRA={NORMALIZATION_LRA}:TP={NORMALIZATION_TRUE_PEAK}']
    
    if metadata:
        for k, v in metadata.items():
            if v:
                cmd += ['-metadata', f'{k}={v}']
    
    cmd += [*audio_args, out_path]
    return cmd

def create_safe_temp_file(filepath, idx):
    """Generate secure temporary file for audio conversion."""
    temp_files_dir = os.path.join(APP_TEMP_DIR, 'temp_files')
    os.makedirs(temp_files_dir, exist_ok=True)
    
    _, ext = os.path.splitext(filepath)
    
    temp_fd, temp_filepath = tempfile.mkstemp(
        suffix=ext, 
        prefix=f"msc_temp_{idx}_", 
        dir=temp_files_dir
    )
    os.close(temp_fd)
    return temp_filepath

def convert_track(filepath, idx, out_folder, high_quality=True, metadata=None, delete_original=True, normalize_audio=False):
    try:
        logger.info(f"Converting track {idx}: {format_file_size_with_extension(filepath)}")
        logger.debug(f"FFmpeg path: {FFMPEG_PATH}")
        logger.debug(f"FFmpeg exists: {os.path.exists(FFMPEG_PATH)}")
        
        if not os.path.isfile(filepath):
            error_msg = f"Input file does not exist: {filepath}"
            logger.error(error_msg)
            return False, error_msg
        
        # Create secure temporary copy for processing
        original_filepath = filepath
        temp_filepath = create_safe_temp_file(filepath, idx)
        
        try:
            shutil.copy2(filepath, temp_filepath)
            filepath = temp_filepath
            logger.debug(f"Created temp copy: {format_file_size_with_extension(temp_filepath)}")
        except Exception as e:
            logger.error(f"Failed to create temp copy: {e}")
            if temp_filepath and os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return False, f"Failed to create temp copy: {e}"
        
        ext = ".ogg"
        fname = f"track{idx}{ext}"
        out_path = os.path.join(out_folder, fname)
        
        # Build FFmpeg command
        cmd = build_ffmpeg_command(filepath, out_path, high_quality, normalize_audio, metadata)
        
        kwargs = {}
        if sys.platform == "win32":
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        logger.debug(f"Input file: {format_file_size_with_extension(filepath)}")
        logger.debug(f"Output file: {format_file_size_with_extension(out_path) if os.path.exists(out_path) else os.path.basename(out_path)}")
        logger.debug(f"Input file exists: {os.path.exists(filepath)}")
        logger.debug(f"Output directory exists: {os.path.exists(os.path.dirname(out_path))}")
        
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **kwargs)
            logger.debug(f"FFmpeg return code: {proc.returncode}")
            logger.debug(f"FFmpeg stdout: {proc.stdout}")
            logger.debug(f"FFmpeg stderr: {proc.stderr}")
            
            if proc.returncode != 0:
                stderr_output = proc.stderr.strip() if proc.stderr else "No error message"
                stdout_output = proc.stdout.strip() if proc.stdout else "No output"
                error_msg = f"FFmpeg error (return code {proc.returncode}): {stderr_output}"
                if stdout_output:
                    error_msg += f" | stdout: {stdout_output}"
                logger.error(error_msg)
                logger.debug(f"FFmpeg command that failed: {' '.join(cmd)}")
                return False, error_msg
        except FileNotFoundError as e:
            error_msg = f"FFmpeg executable not found at {FFMPEG_PATH}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"FFmpeg execution error: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
        finally:
            # Clean up temp file if we created one
            if temp_filepath and os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                    logger.debug(f"Cleaned up temp file: {format_file_size_with_extension(temp_filepath)}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp file {format_file_size_with_extension(temp_filepath)}: {e}")
        
        # Remove original file only if delete_original is True (for downloaded files)
        if delete_original:
            try:
                os.remove(original_filepath)
                logger.debug(f"Removed original file: {format_file_size_with_extension(original_filepath)}")
            except Exception as e:
                logger.warning(f"Failed to remove original file {format_file_size_with_extension(original_filepath)}: {e}")
        else:
            logger.debug(f"Preserving original file: {format_file_size_with_extension(original_filepath)}")
            
        logger.info(f"Successfully converted track {idx}")
        return True, out_path
    except Exception as e:
        error_msg = f"Conversion error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

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

# Debug logging for FFmpeg path resolution
logger.info(f"FFmpeg path resolved to: {FFMPEG_PATH}")
logger.info(f"FFmpeg executable exists: {os.path.exists(FFMPEG_PATH)}")
if hasattr(sys, '_MEIPASS'):
    logger.info(f"Running from PyInstaller bundle: {sys._MEIPASS}")
    # List contents of _MEIPASS to debug resource bundling
    try:
        bundled_files = os.listdir(sys._MEIPASS)
        logger.debug(f"Bundled files in _MEIPASS: {bundled_files}")
        
        # Check if ffmpeg folder exists
        ffmpeg_folder = os.path.join(sys._MEIPASS, 'ffmpeg')
        if os.path.exists(ffmpeg_folder):
            logger.debug(f"FFmpeg folder found, contents: {os.listdir(ffmpeg_folder)}")
            ffmpeg_bin = os.path.join(ffmpeg_folder, 'bin')
            if os.path.exists(ffmpeg_bin):
                logger.debug(f"FFmpeg bin folder found, contents: {os.listdir(ffmpeg_bin)}")
        else:
            logger.warning("FFmpeg folder not found in bundle")
    except Exception as e:
        logger.warning(f"Could not list bundle contents: {e}")
else:
    logger.info("Running from Python script (not bundled)")

class MSCPlaylistGUI:
    """Main GUI application for downloading and converting audio for My Summer Car."""
    
    def __init__(self, master):
        self.master = master
        self.cancel_flag = threading.Event()
        self.current_thread = None
        
        logger.info("Initializing GUI")

        self.small_geometry = "410x175"
        master.title("MSC Playlist Converter")
        master.geometry(self.small_geometry)
        master.update_idletasks()
        width = 410
        height = 175
        x = (master.winfo_screenwidth() // 2) - (width // 2)
        y = (master.winfo_screenheight() // 2) - (height // 2)
        master.geometry(f"{width}x{height}+{x}+{y}")
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
        self.entry.bind('<Button-1>', self.on_entry_click)  # Clear local files when clicking entry
        
        tk.Button(row1, text="Local Audio", command=self.convert_local_files).pack(side="left", padx=(8, 0))

        mode_frame = tk.Frame(main_frame)
        mode_frame.pack(anchor="center", pady=(8, 2))
        self.output_mode_var = tk.StringVar(value="Radio")
        self.output_mode_menu = tk.OptionMenu(mode_frame, self.output_mode_var, "Radio", "CD1", "CD2", "CD3", command=lambda _: self.update_cd_controls())
        self.output_mode_menu.pack(side="left")
        self.cover_path_var = tk.StringVar(value="")
        self.coverart_btn = tk.Button(mode_frame, text="Import Coverart", command=self.import_coverart)
        self.coverart_btn.pack(side="left", padx=(8,0))
        self.high_quality_var = tk.BooleanVar(value=False)
        self.high_quality_checkbox = tk.Checkbutton(mode_frame, text="High Quality", variable=self.high_quality_var)
        self.high_quality_checkbox.pack(side="left", padx=(8, 0))
        
        self.normalize_audio_var = tk.BooleanVar(value=True)
        self.normalize_audio_checkbox = tk.Checkbutton(mode_frame, text="Normalize Audio", variable=self.normalize_audio_var)
        self.normalize_audio_checkbox.pack(side="left", padx=(8, 0))

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

        def show_high_quality_tooltip(event):
            x = self.high_quality_checkbox.winfo_rootx() + self.high_quality_checkbox.winfo_width() + 10
            y = self.high_quality_checkbox.winfo_rooty() + 8
            tooltip = tk.Toplevel(self.high_quality_checkbox)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                tooltip,
                text="High quality .ogg files take a VERY LONG time to import in MSC!",
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

        def show_normalize_audio_tooltip(event):
            x = self.normalize_audio_checkbox.winfo_rootx() + self.normalize_audio_checkbox.winfo_width() + 10
            y = self.normalize_audio_checkbox.winfo_rooty() + 8
            tooltip = tk.Toplevel(self.normalize_audio_checkbox)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                tooltip,
                text="Normalizes audio levels for consistent volume across tracks",
                justify='left',
                background="#ffffe0",
                relief='solid',
                borderwidth=1,
                font=("tahoma", "8", "normal")
            )
            label.pack(ipadx=1)
            self.normalize_audio_tooltip = tooltip

        def hide_normalize_audio_tooltip(event):
            if hasattr(self, 'normalize_audio_tooltip') and self.normalize_audio_tooltip:
                self.normalize_audio_tooltip.destroy()
                self.normalize_audio_tooltip = None

        self.normalize_audio_checkbox.bind("<Enter>", show_normalize_audio_tooltip)
        self.normalize_audio_checkbox.bind("<Leave>", hide_normalize_audio_tooltip)

        self.eta_var = tk.StringVar(value="ETA: --:--")
        self.eta_label = tk.Label(self.button_frame, textvariable=self.eta_var, font=("TkDefaultFont", 9))
        self.eta_label.pack(side="left", padx=(0, 8))

        self.download_button = tk.Button(self.button_frame, text="Start", command=self.start_download)
        self.download_button.pack(side="left", padx=(0, 8))
        self.cancel_button = tk.Button(self.button_frame, text="Cancel", command=self.cancel_download, state='disabled')
        self.cancel_button.pack(side="left", padx=(0, 8))

        self.open_output_btn = tk.Button(self.button_frame, text="Output Folder", command=self.open_output_folder)
        self.open_output_btn.pack(side="right", padx=(8, 0))

        self.playlist = []
        self.thumbnail_path = None
        self.local_files = []  # Store selected local files
        self.update_cd_controls()
        
        # Bind F8 key to open log folder
        self.master.bind('<F8>', lambda event: self.open_log_folder())
        self.master.focus_set()  # Ensure the window can receive key events

    def update_cd_controls(self):
        is_cd = self.output_mode_var.get().startswith("CD")
        state = "normal" if is_cd else "disabled"
        self.coverart_btn.config(state=state)

    def on_entry_click(self, event):
        """Clear local files selection when user clicks on entry field"""
        if hasattr(self, 'local_files') and self.local_files:
            self.local_files = []
            self.entry.config(state='normal')
            self.entry.delete(0, tk.END)
            logger.info("Cleared local files selection - ready for URL input")

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
        logger.error(f"Showing error to user: {msg}")
        self.set_status("Waiting")
        self.clear_current_song()
        messagebox.showerror("Error", msg)

    def show_success(self, files):
        logger.info(f"Successfully processed {len(files)} files")
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

    def open_log_folder(self):
        """Open application log directory in system file explorer."""
        log_dir = os.path.join(APP_TEMP_DIR, 'logs')
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        logger.info(f"Opening log folder: {log_dir}")
        
        try:
            if sys.platform == "win32":
                os.startfile(log_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", log_dir])
            else:
                subprocess.Popen(["xdg-open", log_dir])
        except Exception as e:
            logger.error(f"Failed to open log folder: {e}")
            messagebox.showerror("Error", f"Could not open log folder: {e}")

    def update_eta(self, eta_seconds):
        if eta_seconds is None or eta_seconds < 0:
            self.eta_var.set("ETA: --:--")
            return
        minutes = eta_seconds // 60
        seconds = eta_seconds % 60
        self.eta_var.set(f"ETA: {minutes:02d}:{seconds:02d}")

    def start_download(self):
        url = self.entry.get().strip()
        out_folder = self.get_output_folder()
        is_cd = self.output_mode_var.get().startswith("CD")
        
        logger.info(f"Starting download process. URL: {url}, Output: {out_folder}")
        logger.info(f"High Quality Audio: {'ENABLED' if self.high_quality_var.get() else 'DISABLED (96k, 22kHz)'}")
        logger.info(f"Audio Normalization: {'ENABLED' if self.normalize_audio_var.get() else 'DISABLED'}")

        urls_to_dl = []
        local_files_to_convert = []
        single_track = False
        
        # Check if we have local files selected
        if hasattr(self, 'local_files') and self.local_files and "[" in url and "local files selected]" in url:
            local_files_to_convert = self.local_files
            logger.info(f"Processing {len(local_files_to_convert)} selected local files")
        elif url:
            if is_youtube_track(url) or is_soundcloud_track(url):
                urls_to_dl = get_single_track_info(url)
                single_track = True
                logger.info("Detected single track")
            elif is_soundcloud_playlist(url):
                urls_to_dl = get_soundcloud_playlist_tracks(url)
                logger.info(f"Detected SoundCloud playlist with {len(urls_to_dl)} tracks")
            elif is_youtube_playlist(url):
                urls_to_dl = get_youtube_playlist_videos(url)
                logger.info(f"Detected YouTube playlist with {len(urls_to_dl)} tracks")
            else:
                logger.error(f"Invalid URL format: {url}")
                self.show_error("Invalid link. Please enter a SoundCloud/YouTube link.")
                return

        total = len(urls_to_dl) + len(local_files_to_convert)
        if total == 0:
            self.show_error("No songs to process. Please enter a link or use the Local Audio button.")
            return

        if not os.path.isdir(out_folder):
            try:
                os.makedirs(out_folder)
            except Exception:
                self.show_error(f"Output folder not found and could not be created:\n{out_folder}")
                return

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
            elapsed_times = []
            download_times = []
            convert_times = []
            eta_seconds = None
            stop_eta = threading.Event()
            ROLLING_WINDOW = 8

            def eta_countdown():
                nonlocal eta_seconds
                while not stop_eta.is_set() and eta_seconds is not None and eta_seconds > 0:
                    self.safe_after(self.update_eta, eta_seconds)
                    time.sleep(1)
                    eta_seconds -= 1
                self.safe_after(self.update_eta, eta_seconds)

            eta_thread = None
            try:
                # Process URLs first (if any)
                for idx, media_url in enumerate(urls_to_dl, 1):
                    start_download = time.time()
                    if self.cancel_flag.is_set():
                        self.safe_after(self.set_status, "Cancelled")
                        self.safe_after(self.download_button.config, state='normal')
                        self.safe_after(self.cancel_button.config, state='disabled')
                        return
                    if single_track:
                        track_idx = get_next_track_number(out_folder)
                        filepath, title, thumbnail = download_track(media_url, os.path.join(out_folder, f"track{track_idx}"))
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
                            duration = info.get('duration')
                            if duration:
                                minutes = int(duration // 60)
                                seconds = int(duration % 60)
                                metadata['comment'] = f"Length: {minutes}:{seconds:02d}"
                        else:
                            metadata['title'] = title
                        success, result = convert_track(filepath, track_idx, out_folder, self.high_quality_var.get(), metadata, normalize_audio=self.normalize_audio_var.get())
                    else:
                        track_idx = idx
                        filepath, title, thumbnail = download_track(media_url, os.path.join(out_folder, f"track{track_idx}"))
                        metadata = {'title': title}
                        success, result = convert_track(filepath, track_idx, out_folder, self.high_quality_var.get(), metadata, normalize_audio=self.normalize_audio_var.get())
                    end_download = time.time()
                    download_time = end_download - start_download
                    if not filepath:
                        continue
                    self.safe_after(self.set_current_song, title or "Unknown", track_idx, total)
                    if not success:
                        self.safe_after(self.show_error, result)
                        continue
                    start_convert = time.time()
                    files.append(result)
                    end_convert = time.time()
                    convert_time = end_convert - start_convert
                    download_times.append(download_time)
                    convert_times.append(convert_time)
                    if len(download_times) > ROLLING_WINDOW:
                        download_times.pop(0)
                    if len(convert_times) > ROLLING_WINDOW:
                        convert_times.pop(0)
                    def filter_outliers(times):
                        if not times:
                            return times
                        median = sorted(times)[len(times)//2]
                        return [t for t in times if t < 2*median]
                    filtered_download = filter_outliers(download_times)
                    filtered_convert = filter_outliers(convert_times)
                    avg_download = sum(filtered_download) / len(filtered_download) if filtered_download else 0
                    avg_convert = sum(filtered_convert) / len(filtered_convert) if filtered_convert else 0
                    avg_time = avg_download + avg_convert
                    remaining = total - idx
                    eta_seconds = int(avg_time * remaining)
                    if eta_thread is None or not eta_thread.is_alive():
                        eta_thread = threading.Thread(target=eta_countdown, daemon=True)
                        eta_thread.start()
                    if is_cd and not coverart_done and not coverart_path and thumbnail:
                        # Use cached app temp directory for thumbnail downloads
                        thumb_temp_dir = os.path.join(APP_TEMP_DIR, 'thumbnails')
                        os.makedirs(thumb_temp_dir, exist_ok=True)
                        thumb_path = os.path.join(thumb_temp_dir, f"coverart_{idx}.png")
                        try:
                            import urllib.request
                            urllib.request.urlretrieve(thumbnail, thumb_path)
                            coverart_path = thumb_path
                            coverart_done = True
                        except Exception:
                            pass
                    self.safe_after(self.set_progress, idx, total)

                # Process local files (if any)
                start_idx = len(urls_to_dl)
                for file_idx, localfile in enumerate(local_files_to_convert, 1):
                    idx = start_idx + file_idx
                    if self.cancel_flag.is_set():
                        self.safe_after(self.set_status, "Cancelled")
                        self.safe_after(self.download_button.config, state='normal')
                        self.safe_after(self.cancel_button.config, state='disabled')
                        return
                    fname = os.path.basename(localfile)
                    self.safe_after(self.set_current_song, fname, idx, total)
                    success, result = convert_track(localfile, idx, out_folder, self.high_quality_var.get(), None, delete_original=False, normalize_audio=self.normalize_audio_var.get())
                    if not success:
                        self.safe_after(self.show_error, result)
                        continue
                    files.append(result)
                    self.safe_after(self.set_progress, idx, total)

                stop_eta.set()
                self.safe_after(self.eta_var.set, "ETA: --:--")
                if is_cd and coverart_path:
                    coverart_final = os.path.join(out_folder, "coverart.png")
                    try:
                        img = Image.open(coverart_path)
                        img = img.resize((512,512))
                        img.save(coverart_final)
                    except Exception:
                        pass

                self.safe_after(self.clear_current_song)
                # Clear local files selection after processing
                if local_files_to_convert:
                    self.local_files = []
                    self.safe_after(self.entry.config, state='normal')
                    self.safe_after(self.entry.delete, 0, tk.END)
                    
                if self.cancel_flag.is_set():
                    self.safe_after(self.set_status, "Cancelled")
                elif files:
                    self.safe_after(self.show_success, files)
                else:
                    self.safe_after(self.show_error, "No songs processed.")
                self.safe_after(self.cancel_button.config, state='disabled')
            except Exception as e:
                stop_eta.set()
                self.safe_after(self.show_error, str(e))
                self.safe_after(self.set_status, "Waiting")
                self.safe_after(self.cancel_button.config, state='disabled')
            finally:
                stop_eta.set()
                self.safe_after(self.download_button.config, state='normal')

        self.current_thread = threading.Thread(target=task, daemon=True)
        self.current_thread.start()

    def convert_local_files(self):
        files = filedialog.askopenfilenames(
            title="Select audio files to convert",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.ogg *.flac *.aac *.m4a"),
                ("MP3 files", "*.mp3"),
                ("WAV files", "*.wav"),
                ("OGG files", "*.ogg"),
                ("FLAC files", "*.flac"),
                ("AAC files", "*.aac"),
                ("M4A files", "*.m4a"),
                ("All files", "*.*")
            ]
        )
        if not files:
            return
            
        # Store the selected files for processing when Start button is pressed
        self.local_files = files
        
        # Clear the URL entry and update the UI to show selected files
        self.entry.delete(0, tk.END)
        self.entry.insert(0, f"[{len(files)} local files selected]")
        self.entry.config(state='readonly')
        
        logger.info(f"Selected {len(files)} local audio files for conversion")
        
        # Enable the start button
        self.download_button.config(state='normal')

    def cancel_download(self):
        self.cancel_flag.set()
        self.set_status("Cancelled")
        self.progress['value'] = 0
        self.status_song_var.set("Cancelled")
        self.eta_var.set("ETA: --:--")
        self.cancel_button.config(state='disabled')
        self.download_button.config(state='normal')
        if self.current_thread and self.current_thread.is_alive():
            self.current_thread.join(timeout=1.0)
        self.current_thread = None

if __name__ == "__main__":
    """Application entry point."""
    try:
        logger.info("Creating MSC output directories")
        for sub in ["Radio", "CD1", "CD2", "CD3"]:
            os.makedirs(os.path.join(DEFAULT_MSC_PATH, sub), exist_ok=True)
        
        root = tk.Tk()
        logger.info("Starting GUI application")
        
        # Load application icon
        try:
            icon_path = resource_path('icon.ico')
            if os.path.exists(icon_path):
                root.iconbitmap(icon_path)
            else:
                logger.warning(f"Icon not found: {icon_path}")
        except Exception as e:
            logger.warning(f"Icon load failed: {e}")
        
        app = MSCPlaylistGUI(root)
        logger.info("Starting main application loop")
        root.mainloop()
        
    except Exception as e:
        logger.critical(f"Critical application error: {e}")
        if 'root' in locals():
            messagebox.showerror("Critical Error", f"Application failed to start: {e}")
        raise