import json
import os
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger('discord_bot')

class CommandLogger:
    def __init__(self, base_dir: str = "logs"):
        self.base_dir = base_dir
        self._ensure_directory()
        
    def _ensure_directory(self):
        """Ensure the logs directory exists."""
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
            logger.info(f"Created logs directory: {self.base_dir}")
    
    def _get_log_file(self) -> str:
        """Get the log file path for today."""
        today = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.base_dir, f"commands_{today}.json")
    
    def log_command(self, interaction: Any, response: str):
        """Log a command usage."""
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "user": {
                    "id": str(interaction.user.id),
                    "name": interaction.user.name,
                    "discriminator": interaction.user.discriminator
                },
                "command": {
                    "name": interaction.command.name,
                    "guild_id": str(interaction.guild_id),
                    "guild_name": interaction.guild.name,
                    "channel_id": str(interaction.channel_id),
                    "channel_name": interaction.channel.name
                },
                "response": response
            }
            
            log_file = self._get_log_file()
            logs = []
            
            # Load existing logs if file exists
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            
            # Add new log entry
            logs.append(log_entry)
            
            # Save updated logs
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Logged command usage: {interaction.command.name} by {interaction.user.name}")
            
        except Exception as e:
            logger.error(f"Error logging command: {str(e)}")
    
    def get_command_logs(self, guild_id: str = None, user_id: str = None, command_name: str = None) -> list:
        """Get command logs with optional filters."""
        try:
            log_file = self._get_log_file()
            if not os.path.exists(log_file):
                return []
            
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            
            # Apply filters
            filtered_logs = logs
            if guild_id:
                filtered_logs = [log for log in filtered_logs if log['command']['guild_id'] == guild_id]
            if user_id:
                filtered_logs = [log for log in filtered_logs if log['user']['id'] == user_id]
            if command_name:
                filtered_logs = [log for log in filtered_logs if log['command']['name'] == command_name]
            
            return filtered_logs
            
        except Exception as e:
            logger.error(f"Error getting command logs: {str(e)}")
            return []

# Create a global command logger instance
command_logger = CommandLogger() 