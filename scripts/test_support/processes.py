"""Wait for every owned child even if another child's cleanup fails."""

import subprocess


def stop_processes(*processes):
    errors = []
    for process in processes:
        if process is None:
            continue
        try:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        except (OSError, subprocess.SubprocessError) as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("Owned process cleanup failed", errors)
