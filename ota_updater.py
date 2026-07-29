import ujson
import uos as os
import uhashlib
import ubinascii
import urequests
import machine
import time
import gc

VERSION_FILE = "firmware_version.txt"

# Replace with your actual GitHub raw manifest URL once your repo is set up, e.g.:
# "https://raw.githubusercontent.com/<yourusername>/<yourrepo>/main/manifest.json"
MANIFEST_URL = "https://raw.githubusercontent.com/YOURUSERNAME/YOURREPO/main/manifest.json"


def get_current_version():
    try:
        with open(VERSION_FILE, "r") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"


def _set_current_version(version):
    with open(VERSION_FILE, "w") as f:
        f.write(version)


def _sha256_hex(data):
    h = uhashlib.sha256()
    h.update(data)
    return ubinascii.hexlify(h.digest()).decode()


def _download(url):
    response = urequests.get(url)
    try:
        data = response.content
    finally:
        response.close()
    return data


def check_for_update(display=None):
    """Checks the manifest for a version different from the one currently
    installed. If found, downloads every listed file to a staging filename
    and verifies its sha256 hash. Only if EVERY file downloads and verifies
    cleanly does it swap them all into place and reboot - if anything fails
    at any point, the currently running files are left completely untouched.

    Returns True if an update was applied (device reboots as part of this),
    False if already up to date or the check/update failed."""
    gc.collect()
    current_version = get_current_version()
    print("Current firmware version:", current_version)

    try:
        manifest_resp = urequests.get(MANIFEST_URL)
        manifest = manifest_resp.json()
        manifest_resp.close()
    except (OSError, ValueError) as e:
        print("OTA check failed - could not fetch manifest:", e)
        return False

    remote_version = manifest.get("version", "")
    files = manifest.get("files", {})

    if not remote_version or not files:
        print("OTA manifest is missing version or files.")
        return False

    if remote_version == current_version:
        print("Already up to date.")
        return False

    print("New version available: {} -> {}".format(current_version, remote_version))
    if display:
        display.show("Update Found", "", "v" + remote_version, "Downloading...")

    staged = []
    try:
        for filename, info in files.items():
            url = info["url"]
            expected_hash = info.get("sha256")

            print("Downloading", filename)
            data = _download(url)

            if expected_hash:
                actual_hash = _sha256_hex(data)
                if actual_hash != expected_hash:
                    raise ValueError("Hash mismatch for {}".format(filename))

            staging_name = filename + ".new"
            with open(staging_name, "wb") as f:
                f.write(data)
            staged.append((staging_name, filename))
            del data
            gc.collect()

    except (OSError, ValueError, KeyError) as e:
        print("OTA update failed during download - leaving current files untouched:", e)
        for staging_name, _ in staged:
            try:
                os.remove(staging_name)
            except OSError:
                pass
        if display:
            display.show("Update Failed", "", "Keeping current", "version")
        return False

    print("All files downloaded and verified. Applying update...")
    if display:
        display.show("Applying Update", "", "Do not power off...")

    for staging_name, filename in staged:
        try:
            os.remove(filename)
        except OSError:
            pass
        os.rename(staging_name, filename)

    _set_current_version(remote_version)
    print("Update applied. Restarting...")
    if display:
        display.show("Update Complete", "", "v" + remote_version, "Restarting...")

    time.sleep(2)
    machine.reset()
    return True
