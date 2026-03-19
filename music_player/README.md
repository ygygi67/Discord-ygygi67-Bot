# Music Player Application

A simple music player application with a graphical user interface, playlist management, and automatic playback features.

## Features

- Play, pause, stop, next, and previous song controls
- Volume control
- Progress bar with seek functionality
- Playlist management
- Automatic playback of next song
- Support for MP3, WAV, and OGG audio formats

## Requirements

- Python 3.8 or higher
- PyQt6
- pygame
- mutagen

## Installation

1. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install the required packages:
```bash
pip install -r requirements.txt
```

## Usage

1. Run the application:
```bash
python music_player.py
```

2. Add songs to the playlist using the "Add Song" button
3. Use the control buttons to manage playback:
   - Play/Pause: Toggle playback
   - Stop: Stop current song
   - Next/Previous: Navigate through playlist
   - Volume Slider: Adjust volume
   - Progress Slider: Seek through current song

## Controls

- Add Song: Add music files to the playlist
- Play/Pause: Toggle playback of current song
- Stop: Stop current song
- Next: Play next song in playlist
- Previous: Play previous song in playlist
- Volume Slider: Adjust playback volume
- Progress Slider: Seek through current song

## Notes

- The application supports MP3, WAV, and OGG audio formats
- Songs will automatically play in sequence
- The playlist is cleared when the application is closed 