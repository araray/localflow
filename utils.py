
import logging
import sys
from pathlib import Path

from config import OutputConfig



class OutputHandler:
    """Handles workflow output routing and file management."""
    def __init__(self, config: OutputConfig):
        if not isinstance(config.file, (Path, type(None))):
            raise TypeError(f"`file` in OutputConfig must be a Path or None, got {type(config.file)}")
        self.config = config
        self._file_handle = None

    def __enter__(self):
        """Set up output handling and ensure file creation."""
        if self.config and self.config.file and self.config.mode in (OutputMode.FILE, OutputMode.BOTH):
            try:
                # Ensure parent directories exist
                self.config.file.parent.mkdir(parents=True, exist_ok=True)

                # Open file with appropriate mode
                mode = 'a' if self.config.append else 'w'
                self._file_handle = open(self.config.file, mode)
                logging.debug(f"Output file {self.config.file} created with mode '{mode}'.")
            except Exception as e:
                raise ValueError(f"Failed to initialize output file: {e}") from e
        return self

    def write(self, content: str):
        """Write content to configured outputs."""
        if self._file_handle and self.config.mode in (OutputMode.FILE, OutputMode.BOTH):
            self._file_handle.write(content)
            self._file_handle.flush()
            logging.debug(f"Written to file {self.config.file}: {content.strip()}")
        if self.config.stdout and self.config.mode in (OutputMode.STDOUT, OutputMode.BOTH):
            sys.stdout.write(content)
            sys.stdout.flush()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting the context."""
        if self._file_handle:
            try:
                self._file_handle.close()
                logging.debug(f"Output file {self.config.file} closed.")
            except Exception as e:
                logging.error(f"Failed to close output file {self.config.file}: {e}")