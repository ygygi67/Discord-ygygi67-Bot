import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger('discord_bot')

class Storage:
    def __init__(self, filename="data/storage.json"):
        self.filename = filename
        self.data = {}
        self._ensure_directory()
        self.load_data()

    def _ensure_directory(self):
        """Ensure the directory for the storage file exists."""
        directory = os.path.dirname(self.filename)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"Created directory for storage: {directory}")

    def load_data(self):
        """Load data from file."""
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r') as f:
                    self.data = json.load(f)
            else:
                self.data = {}
                self.save_data()
        except Exception as e:
            logger.error(f"Error loading data: {str(e)}")
            self.data = {}

    def save_data(self):
        """Save data to file."""
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving data: {str(e)}")

    def save_data_for_guild(self, guild_id: int, key: str, value: Any):
        """Save data for a specific guild."""
        try:
            if str(guild_id) not in self.data:
                self.data[str(guild_id)] = {}
            self.data[str(guild_id)][key] = value
            self.save_data()
            logger.info(f"Saved data for guild {guild_id}")
        except Exception as e:
            logger.error(f"Error saving data for guild {guild_id}: {str(e)}")

    def load_data_for_guild(self, guild_id: int, key: str) -> Any:
        """Load data for a specific guild."""
        try:
            return self.data.get(str(guild_id), {}).get(key)
        except Exception as e:
            logger.error(f"Error loading data for guild {guild_id}: {str(e)}")
            return None

    def delete_data_for_guild(self, guild_id: int, key: str):
        """Delete data for a specific guild."""
        try:
            if str(guild_id) in self.data and key in self.data[str(guild_id)]:
                del self.data[str(guild_id)][key]
                self.save_data()
                logger.info(f"Deleted data for guild {guild_id}")
        except Exception as e:
            logger.error(f"Error deleting data for guild {guild_id}: {str(e)}")

# Create a global instance
storage = Storage() 