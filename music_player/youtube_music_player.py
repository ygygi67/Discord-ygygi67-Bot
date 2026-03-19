import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QPushButton, QLabel, QListWidget, 
                           QLineEdit, QSlider, QStyle, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
import pygame
from pytube import YouTube, Search
import tempfile
import threading

class DownloadThread(QThread):
    download_complete = pyqtSignal(str)
    download_error = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            yt = YouTube(self.url)
            audio = yt.streams.filter(only_audio=True).first()
            temp_dir = tempfile.gettempdir()
            file_path = audio.download(output_path=temp_dir)
            self.download_complete.emit(file_path)
        except Exception as e:
            self.download_error.emit(str(e))

class SearchThread(QThread):
    search_complete = pyqtSignal(list)
    search_error = pyqtSignal(str)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        try:
            search = Search(self.query)
            results = []
            for video in search.results[:5]:  # Get top 5 results
                results.append((video.title, video.watch_url))
            self.search_complete.emit(results)
        except Exception as e:
            self.search_error.emit(str(e))

class YouTubeMusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Music Player")
        self.setGeometry(100, 100, 800, 600)
        
        # Initialize pygame mixer
        pygame.mixer.init()
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Create search area
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter song name or YouTube URL")
        self.search_input.returnPressed.connect(self.handle_search)
        search_layout.addWidget(self.search_input)
        
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.handle_search)
        search_layout.addWidget(self.search_button)
        
        layout.addLayout(search_layout)
        
        # Create search results list
        self.search_results = QListWidget()
        self.search_results.itemDoubleClicked.connect(self.play_selected_result)
        layout.addWidget(self.search_results)
        
        # Create playlist widget
        self.playlist = QListWidget()
        layout.addWidget(self.playlist)
        
        # Create control buttons
        controls_layout = QHBoxLayout()
        
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
        
    def handle_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
            
        if query.startswith(('http://', 'https://')):
            # Handle direct YouTube URL
            self.download_thread = DownloadThread(query)
            self.download_thread.download_complete.connect(self.add_to_playlist)
            self.download_thread.download_error.connect(self.show_error)
            self.download_thread.start()
        else:
            # Handle search query
            self.search_thread = SearchThread(query)
            self.search_thread.search_complete.connect(self.show_search_results)
            self.search_thread.search_error.connect(self.show_error)
            self.search_thread.start()
            
    def show_search_results(self, results):
        self.search_results.clear()
        for title, url in results:
            self.search_results.addItem(title)
            self.search_results.item(self.search_results.count() - 1).setData(Qt.ItemDataRole.UserRole, url)
            
    def play_selected_result(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        self.download_thread = DownloadThread(url)
        self.download_thread.download_complete.connect(self.add_to_playlist)
        self.download_thread.download_error.connect(self.show_error)
        self.download_thread.start()
        
    def add_to_playlist(self, file_path):
        self.song_list.append(file_path)
        self.temp_files.append(file_path)
        self.playlist.addItem(os.path.basename(file_path))
        
        if self.current_song is None:
            self.current_index = 0
            self.current_song = self.song_list[0]
            self.play_song()
            
    def show_error(self, error_message):
        QMessageBox.critical(self, "Error", error_message)
        
    def play_pause(self):
        if not self.song_list:
            return
            
        if self.current_song is None:
            self.current_index = 0
            self.current_song = self.song_list[0]
            self.play_song()
        else:
            if self.is_playing:
                pygame.mixer.music.pause()
                self.is_playing = False
                self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            else:
                pygame.mixer.music.unpause()
                self.is_playing = True
                self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
                
    def stop(self):
        pygame.mixer.music.stop()
        self.is_playing = False
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.progress_slider.setValue(0)
        
    def next_song(self):
        if not self.song_list:
            return
            
        self.current_index = (self.current_index + 1) % len(self.song_list)
        self.current_song = self.song_list[self.current_index]
        self.play_song()
        
    def previous_song(self):
        if not self.song_list:
            return
            
        self.current_index = (self.current_index - 1) % len(self.song_list)
        self.current_song = self.song_list[self.current_index]
        self.play_song()
        
    def play_song(self):
        if self.current_song:
            pygame.mixer.music.load(self.current_song)
            pygame.mixer.music.play()
            self.is_playing = True
            self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.playlist.setCurrentRow(self.current_index)
            
    def set_position(self, position):
        if self.current_song:
            pygame.mixer.music.set_pos(position)
            
    def set_volume(self, volume):
        pygame.mixer.music.set_volume(volume / 100)
        
    def update_progress(self):
        if self.is_playing:
            current_pos = pygame.mixer.music.get_pos() / 1000  # Convert to seconds
            if current_pos > 0:
                self.progress_slider.setValue(int(current_pos))
                
            # Check if song has ended
            if not pygame.mixer.music.get_busy() and self.is_playing:
                self.next_song()
                
    def closeEvent(self, event):
        pygame.mixer.quit()
        # Clean up temporary files
        for file in self.temp_files:
            try:
                os.remove(file)
            except:
                pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = YouTubeMusicPlayer()
    player.show()
    sys.exit(app.exec()) 