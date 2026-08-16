#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author :  ELFO

import os
import subprocess


def main():
    print(
        " ▌ ▐·▪  ·▄▄▄▄  ▄▄▄ .      ·▄▄▄▄       ▄▄▌ ▐ ▄▌ ▐ ▄ ▄▄▌         ▄▄▄· ·▄▄▄▄  ▄▄▄ .▄▄▄  "
    )
    print(
        "▪█·█▌██ ██▪ ██ ▀▄.▀·▪     ██▪ ██▪     ██· █▌▐█•█▌▐███•  ▪     ▐█ ▀█ ██▪ ██ ▀▄.▀·▀▄ █·"
    )
    print(
        "▐█▐█•▐█·▐█· ▐█▌▐▀▀▪▄ ▄█▀▄ ▐█· ▐█▌▄█▀▄ ██▪▐█▐▐▌▐█▐▐▌██▪   ▄█▀▄ ▄█▀▀█ ▐█· ▐█▌▐▀▀▪▄▐▀▀▄ "
    )
    print(
        " ███ ▐█▌██. ██ ▐█▄▄▌▐█▌.▐▌██. ██▐█▌.▐▌▐█▌██▐█▌██▐█▌▐█▌▐▌▐█▌.▐▌▐█ ▪▐▌██. ██ ▐█▄▄▌▐█•█▌"
    )
    print(
        ". ▀  ▀▀▀▀▀▀▀▀•  ▀▀▀  ▀█▄▀▪▀▀▀▀▀• ▀█▄▀▪ ▀▀▀▀ ▀▪▀▀ █▪.▀▀▀  ▀█▄▀▪ ▀  ▀ ▀▀▀▀▀•  ▀▀▀ .▀  ▀"
    )
    print(
        "▄▄▄▄·  ▄· ▄▌                                                                         "
    )
    print(
        "▐█ ▀█▪▐█▪██▌                                                                         "
    )
    print(
        "▐█▀▀█▄▐█▌▐█▪                                                                         "
    )
    print(
        "██▄▪▐█ ▐█▀·.                                                                         "
    )
    print(
        "·▀▀▀▀   ▀ •                                                                          "
    )
    print(
        ".▄▄ · • ▌ ▄ ·.       ▄ •▄  ▄· ▄▌                                                     "
    )
    print(
        "▐█ ▀. ·██ ▐███▪▪     █▌▄▌▪▐█▪██▌                                                     "
    )
    print(
        "▄▀▀▀█▄▐█ ▌▐▌▐█· ▄█▀▄ ▐▀▀▄·▐█▌▐█▪                                                     "
    )
    print(
        "▐█▄▪▐███ ██▌▐█▌▐█▌.▐▌▐█.█▌ ▐█▀·.                                                     "
    )
    print(
        " ▀▀▀▀ ▀▀  █▪▀▀▀ ▀█▄▀▪·▀  ▀  ▀ •                                                      "
    )

    url = input("Du willst ein Video herunterladen:\nEnter URL: ")

    # Download the video
    try:
        subprocess.run(["yt-dlp", "-f", "b", url], check=True)
    except subprocess.CalledProcessError:
        print("Fehler beim Herunterladen des Videos.")


if __name__ == "__main__":
    main()
