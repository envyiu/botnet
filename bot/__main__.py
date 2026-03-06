#!/usr/bin/env python3
"""Entry point: python -m bot"""

import threading

from .config import BOT_ID, P2P_PORT, BOOTSTRAP_PEERS, CMD_QUEUE, CMD_REF
from .p2p import p2p_listener
from .commands import command_processor


def main():
    print(f"--- BOT {BOT_ID} ---")
    print(f"    P2P: :{P2P_PORT}")
    print(f"    Peers: {len(BOOTSTRAP_PEERS)}")
    print(f"-------------------")

    threading.Thread(target=p2p_listener, args=(CMD_QUEUE, CMD_REF), daemon=True).start()
    command_processor()


if __name__ == "__main__":
    main()
