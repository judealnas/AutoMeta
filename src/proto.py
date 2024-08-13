import time
import os
import logging
import click
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class FileMonitorHandler(FileSystemEventHandler):
    def __init__(self, file_extensions, log_file):
        self.file_extensions = file_extensions
        self.log_file = log_file

    def on_created(self, event):
        self.process(event, "created")

    def on_modified(self, event):
        self.process(event, "modified")

    def process(self, event, event_type):
        if event.is_directory:
            return None

        _, ext = os.path.splitext(event.src_path)
        if ext.lower() in self.file_extensions:
            logging.info(f"File {event.src_path} has been {event_type}.")
            print(f"File {event.src_path} has been {event_type}.")


def setup_logging(log_file):
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def start_monitoring(path, file_extensions, log_file):
    setup_logging(log_file)
    event_handler = FileMonitorHandler(file_extensions, log_file)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()

    try:
        logging.info(f"Started monitoring directory: {path}")
        print(f"Monitoring directory: {path}")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    logging.info(f"Stopped monitoring directory: {path}")


@click.command()
@click.option("--path", "-p", default=".", help="Directory to monitor.")
@click.option(
    "--extensions",
    "-e",
    default=".mp3,.flac",
    help="Comma-separated list of file extensions to monitor.",
)
def main(path, extensions):
    # Process file extensions
    file_extensions = {ext.strip().lower() for ext in extensions.split(",")}
    log_file_path = os.path.join(path, ".autometa", "logs")

    start_monitoring(path, file_extensions, log_file_path)


if __name__ == "__main__":
    main()
