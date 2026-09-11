"""Send a local shortcut action without importing Qt or opening the glasses."""
import socket
import sys


if __name__ == '__main__':
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        try:
            client.sendto(sys.argv[2].encode(), sys.argv[1])
        except (FileNotFoundError, ConnectionRefusedError):
            pass
