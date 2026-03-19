import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QPushButton, QLabel, QListWidget, 
                           QFileDialog, QSlider, QStyle, QLineEdit, QMessageBox, QProgressBar)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoWidget
import pygame
import mutagen
from mutagen.mp3 import MP3
import time
import tempfile
import re
import subprocess
import yt_dlp
import json
import urllib.parse

print("QVideoWidget imported successfully!")

class DownloadThread(QThread):
    download_complete = pyqtSignal(str, str, str)  # file_path, title, video_url
    download_error = pyqtSignal(str)
    download_progress = pyqtSignal(int)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        try:
            temp_dir = tempfile.gettempdir()
            
            # Configure yt-dlp options
            ydl_opts = {
                'format': 'best[ext=mp4]',  # Get the best quality MP4
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [self.progress_hook],
                'extract_flat': True,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'prefer_insecure': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            }
            
            # Check if input is a URL or search query
            if self.query.startswith(('http://', 'https://')):
                url = self.query
            else:
                # It's a search query, add ytsearch prefix
                url = f"ytsearch1:{self.query}"
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # First check if video is available
                try:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        raise Exception("Could not get video information")
                    
                    # If it's a search result, get the first video
                    if 'entries' in info:
                        info = info['entries'][0]
                        
                    # Check if video is available
                    if info.get('availability') == 'private':
                        raise Exception("This video is private")
                    elif info.get('availability') == 'unavailable':
                        raise Exception("This video is not available")
                    elif info.get('age_limit') and info['age_limit'] > 0:
                        # Try to download without age verification
                        ydl_opts['age_limit'] = 0
                except yt_dlp.utils.DownloadError as e:
                    if 'Video unavailable' in str(e):
                        raise Exception("This video is not available")
                    elif 'Sign in to confirm your age' in str(e):
                        raise Exception("This video is age-restricted. Please try a different video.")
                    else:
                        raise
                
                # Now try to download
                title = re.sub(r'[\\/*?:"<>|]', "", info['title'])
                final_mp4 = os.path.join(temp_dir, f"{title}.mp4")
                
                # Download the video
                ydl.download([url])
                
                self.download_complete.emit(final_mp4, title, info['webpage_url'])
                
        except yt_dlp.utils.DownloadError as e:
            if 'Video unavailable' in str(e):
                self.download_error.emit("This video is not available")
            elif 'Sign in to confirm your age' in str(e):
                self.download_error.emit("This video is age-restricted. Please try a different video.")
            else:
                self.download_error.emit(f"Download error: {str(e)}")
        except Exception as e:
            self.download_error.emit(str(e))
            
    def progress_hook(self, d):
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    percentage = (downloaded / total) * 100
                    self.download_progress.emit(int(percentage))
            except:
                pass

class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Player")
        self.setGeometry(100, 100, 1200, 800)  # Increased window size
        
        # Initialize pygame mixer
        pygame.mixer.init()
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Create video widget
        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget)
        
        # Create media player
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        
        # Create URL input
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter YouTube URL or search query")
        self.url_input.returnPressed.connect(self.download_from_youtube)
        url_layout.addWidget(self.url_input)
        
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.download_from_youtube)
        url_layout.addWidget(self.download_button)
        
        layout.addLayout(url_layout)
        
        # Create status label
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        
        # Create progress bar for download
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        layout.addWidget(self.download_progress)
        
        # Create playlist widget
        self.playlist = QListWidget()
        layout.addWidget(self.playlist)
        
        # Create control buttons
        controls_layout = QHBoxLayout()
        
        # Add song button
        self.add_button = QPushButton("Add Local Song")
        self.add_button.clicked.connect(self.add_song)
        controls_layout.addWidget(self.add_button)
        
        # Play button
        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_button.clicked.connect(self.play_pause)
        controls_layout.addWidget(self.play_button)
        
        # Stop button
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.clicked.connect(self.stop)
        controls_layout.addWidget(self.stop_button)
        
        # Next button
        self.next_button = QPushButton()
        self.next_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.next_button.clicked.connect(self.next_song)
        controls_layout.addWidget(self.next_button)
        
        # Previous button
        self.prev_button = QPushButton()
        self.prev_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.prev_button.clicked.connect(self.previous_song)
        controls_layout.addWidget(self.prev_button)
        
        layout.addLayout(controls_layout)
        
        # Create progress slider
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 100)
        self.progress_slider.sliderMoved.connect(self.set_position)
        layout.addWidget(self.progress_slider)
        
        # Create volume slider
        volume_layout = QHBoxLayout()
        self.volume_label = QLabel("Volume:")
        volume_layout.addWidget(self.volume_label)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.set_volume)
        volume_layout.addWidget(self.volume_slider)
        
        layout.addLayout(volume_layout)
        
        # Initialize variables
        self.current_song = None
        self.song_list = []
        self.current_index = -1
        self.is_playing = False
        self.temp_files = []
        
        # Create timer for progress updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(1000)  # Update every second
        
    def download_from_youtube(self):
        query = self.url_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Error", "Please enter a YouTube URL or search query")
            return
            
        self.status_label.setText("Downloading...")
        self.download_button.setEnabled(False)
        self.url_input.setEnabled(False)
        self.download_progress.setValue(0)
        
        self.download_thread = DownloadThread(query)
        self.download_thread.download_complete.connect(self.add_downloaded_song)
        self.download_thread.download_error.connect(self.show_error)
        self.download_thread.download_progress.connect(self.update_download_progress)
        self.download_thread.start()
        
    def update_download_progress(self, progress):
        self.download_progress.setValue(progress)
        
    def add_downloaded_song(self, file_path, title, video_url):
        self.song_list.append((file_path, video_url))
        self.temp_files.append(file_path)
        self.playlist.addItem(title)
        
        if self.current_song is None:
            self.current_index = 0
            self.current_song = self.song_list[0][0]
            self.play_song()
            
        self.status_label.setText("Ready")
        self.download_button.setEnabled(True)
        self.url_input.setEnabled(True)
        self.url_input.clear()
        self.download_progress.setValue(0)
            
    def show_error(self, error_message):
        self.status_label.setText("Error: " + error_message)
        self.download_button.setEnabled(True)
        self.url_input.setEnabled(True)
        self.download_progress.setValue(0)
        QMessageBox.critical(self, "Error", f"Failed to download: {error_message}")
        
    def add_song(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Music Files",
            "",
            "Audio Files (*.mp3 *.wav *.ogg)"
        )
        
        for file in files:
            self.song_list.append((file, None))
            self.playlist.addItem(os.path.basename(file))
            
    def play_pause(self):
        if not self.song_list:
            return
            
        if self.current_song is None:
            self.current_index = 0
            self.current_song = self.song_list[0][0]
            self.play_song()
        else:
            if self.is_playing:
                self.media_player.pause()
                self.is_playing = False
                self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            else:
                self.media_player.play()
                self.is_playing = True
                self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
                
    def stop(self):
        self.media_player.stop()
        self.is_playing = False
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.progress_slider.setValue(0)
        
    def next_song(self):
        if not self.song_list:
            return
            
        self.current_index = (self.current_index + 1) % len(self.song_list)
        self.current_song = self.song_list[self.current_index][0]
        self.play_song()
        
    def previous_song(self):
        if not self.song_list:
            return
            
        self.current_index = (self.current_index - 1) % len(self.song_list)
        self.current_song = self.song_list[self.current_index][0]
        self.play_song()
        
    def play_song(self):
        if self.current_song:
            self.media_player.setSource(QUrl.fromLocalFile(self.current_song))
            self.media_player.play()
            self.is_playing = True
            self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.playlist.setCurrentRow(self.current_index)
            
            # Get song duration
            try:
                audio = MP3(self.current_song)
                self.song_duration = audio.info.length
            except:
                self.song_duration = 0
                
    def set_position(self, position):
        if self.current_song and self.song_duration > 0:
            position_seconds = (position / 100) * self.song_duration
            self.media_player.setPosition(int(position_seconds * 1000))  # Convert to milliseconds
            
    def set_volume(self, volume):
        self.media_player.setVolume(volume)
        
    def update_progress(self):
        if self.is_playing and self.song_duration > 0:
            current_pos = self.media_player.position() / 1000  # Convert to seconds
            if current_pos > 0:
                progress = (current_pos / self.song_duration) * 100
                self.progress_slider.setValue(int(progress))
                
            # Check if song has ended
            if self.media_player.playbackState() == QMediaPlayer.PlaybackState.StoppedState and self.is_playing:
                self.next_song()
                
    def closeEvent(self, event):
        self.media_player.stop()
        # Clean up temporary files
        for file in self.temp_files:
            try:
                os.remove(file)
            except:
                pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = MusicPlayer()
    player.show()
    sys.exit(app.exec()) 