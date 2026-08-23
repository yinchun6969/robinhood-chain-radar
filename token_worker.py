#!/usr/bin/env python3
import monitor


def main(stop_event=None):
    monitor.token_radar.run_worker(stop_event)


if __name__ == "__main__":
    main()
