#vMSC Playlist Converter

## Overview
The MSC Playlist Converter is a Python application designed to facilitate the downloading and conversion of audio tracks from YouTube and SoundCloud into a format suitable for use in the game "My Summer Car." The application features a user-friendly graphical interface built with Tkinter.

## Features
- Download tracks from YouTube and SoundCloud playlists or individual tracks.
- Convert downloaded audio files into OGG format.
- Manage output folders for different media types (Radio, CD1, CD2, CD3).
- Import cover art for CD outputs.
- Progress tracking and logging for downloads and conversions.

## Requirements
To run the MSC Playlist Converter, you need to have the following Python packages installed:
- yt-dlp
- Pillow
- Tkinter (usually included with Python installations)

You can install the required packages using pip. Make sure to create a virtual environment for your project:

```bash
pip install -r requirements.txt
```

## Installation
1. Clone the repository or download the source code.
2. Ensure you have Python installed on your system.
3. Install the required packages as mentioned above.
4. Run the application using the following command:

```bash
python src/MSCPlaylistConverter.py
```

## Usage
1. Open the application.
2. Enter a YouTube or SoundCloud playlist/track link in the provided input field.
3. Select the output mode (Radio, CD1, CD2, CD3).
4. Click on "Start" to begin the download and conversion process.
5. Monitor the progress and logs displayed in the application.

## Output
The converted audio files will be saved in the designated output folder based on the selected mode. Cover art can also be imported for CD outputs.
When downloading a single track it will add it to existing ones.
