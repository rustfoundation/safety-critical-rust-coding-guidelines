import sys
import time
import threading
class Spinner:
    def __init__(self, message="Building", enabled=True):
        self.running = False
        self.thread = None
        self.message = message
        self.enabled = enabled and sys.stderr.isatty()

    def _spin(self):
        spinner = "|/-\\"
        idx = 0
        while self.running:
            sys.stderr.write(f"\r{self.message} {spinner[idx % len(spinner)]}")
            sys.stderr.flush()
            idx += 1
            time.sleep(0.1)

    def start(self):
        if not self.enabled:
            return
        self.running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self, final_message=None):
        if not self.enabled:
            return
        self.running = False
        self.thread.join()
        sys.stderr.write("\r" + " " * 50 + "\r")  
        if final_message:
            sys.stderr.write(final_message + "\n")
        sys.stderr.flush()
