"""
Configuration & Device Profile management for HikView.
Handles saving/loading NVR settings, multi-source camera channels (Primary NVR, Secondary NVR,
Standalone ONVIF/RTSP IP cameras), device brand presets, and dynamic UI layout preferences.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote


# Supported Device Brand / RTSP URL format presets
DEVICE_PRESETS: List[Tuple[str, str]] = [
    ("isapi", "Hikvision / HiLook / OEM NVR & Cameras (ISAPI)"),
    ("legacy", "Hikvision / HiLook Legacy Firmware (/h264/chX/...)"),
    ("dahua", "Dahua / Amcrest / Lorex NVR & Cameras"),
    ("reolink", "Reolink NVR / IP Cameras"),
    ("unv", "Uniview (UNV) / ONVIF Standard RTSP"),
    ("tp_link", "TP-Link Tapo / VIGI IP Cameras"),
    ("custom", "Generic ONVIF / Custom RTSP URL"),
]


def get_preset_label(url_style: str) -> str:
    """Return human-readable brand label for a url_style key."""
    for key, label in DEVICE_PRESETS:
        if key == url_style:
            return label
    return "Hikvision / HiLook / ONVIF Device"


def format_rtsp_url_by_style(
    url_style: str,
    host: str,
    port: int,
    username: str,
    password: str,
    channel_num: int = 1,
    stream_type: str = "main",
    custom_main_url: str = "",
    custom_sub_url: str = "",
) -> str:
    """
    Build a complete RTSP URL for any supported NVR/camera brand preset or custom RTSP override.
    """
    # 1. Check explicit custom URL overrides first
    if stream_type == "sub" and custom_sub_url.strip():
        return custom_sub_url.strip()
    if custom_main_url.strip():
        return custom_main_url.strip()

    clean_host = host.strip()
    if not clean_host:
        return ""

    auth_part = ""
    clean_user = username.strip()
    if clean_user:
        enc_user = quote(clean_user, safe="")
        enc_pass = quote(password or "", safe="")
        auth_part = f"{enc_user}:{enc_pass}@"

    ch = max(1, int(channel_num))
    is_main = (stream_type == "main")

    if url_style == "legacy":
        s_name = "main" if is_main else "sub"
        return f"rtsp://{auth_part}{clean_host}:{port}/h264/ch{ch}/{s_name}/av_stream"
    elif url_style == "dahua":
        subtype = 0 if is_main else 1
        return f"rtsp://{auth_part}{clean_host}:{port}/cam/realmonitor?channel={ch}&subtype={subtype}"
    elif url_style == "reolink":
        s_name = "main" if is_main else "sub"
        return f"rtsp://{auth_part}{clean_host}:{port}/h264Preview_{ch:02d}_{s_name}"
    elif url_style == "unv":
        s_idx = 0 if is_main else 1
        return f"rtsp://{auth_part}{clean_host}:{port}/unicast/c{ch}/s{s_idx}/live"
    elif url_style == "tp_link":
        s_idx = 1 if is_main else 2
        return f"rtsp://{auth_part}{clean_host}:{port}/stream{s_idx}"
    elif url_style == "custom":
        # Default ONVIF/generic fallback if no custom_rtsp_url was provided
        s_idx = 1 if is_main else 2
        return f"rtsp://{auth_part}{clean_host}:{port}/stream{s_idx}"
    else:
        # Standard Hikvision / HiLook / OEM ISAPI format (/Streaming/Channels/101)
        stream_idx = 1 if is_main else 2
        hik_channel = ch * 100 + stream_idx
        return f"rtsp://{auth_part}{clean_host}:{port}/Streaming/Channels/{hik_channel}"


def get_config_dir() -> Path:
    """Return the user configuration directory for HikView."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "HikView"
    else:
        base = Path.home() / ".hikview"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_snapshots_dir() -> Path:
    """Return the default snapshots directory."""
    pics = Path.home() / "Pictures" / "HikView"
    pics.mkdir(parents=True, exist_ok=True)
    return pics


@dataclass
class CameraChannelConfig:
    """
    Configuration for an individual camera channel (1..16).
    Can belong to the Primary NVR (`source_type="primary_nvr"`), a Secondary NVR (`source_type="secondary_nvr"`),
    or a Standalone ONVIF/RTSP IP Camera (`source_type="standalone"`).
    """
    channel_id: int
    name: str
    enabled: bool = True
    source_type: str = "primary_nvr"      # "primary_nvr", "secondary_nvr", "standalone"
    remote_channel_id: int = 0            # Channel # on the target NVR (defaults to channel_id if 0)
    use_custom_host: bool = False         # True when source_type != "primary_nvr" or custom host is used
    custom_brand: str = "isapi"           # Brand preset for secondary NVR or standalone camera
    custom_host: str = ""
    custom_port: int = 554
    custom_username: str = ""
    custom_password: str = ""
    custom_rtsp_url: str = ""             # Optional full RTSP Main Stream URL override
    custom_sub_rtsp_url: str = ""         # Optional full RTSP Sub Stream URL override
    preferred_stream: str = "auto"        # "auto", "main", "sub"

    def __post_init__(self):
        if self.remote_channel_id <= 0:
            self.remote_channel_id = self.channel_id
        # Backward compatibility: if old config had use_custom_host or custom_rtsp_url set
        if self.source_type == "primary_nvr":
            if self.custom_rtsp_url.strip():
                self.source_type = "standalone"
                self.custom_brand = "custom"
                self.use_custom_host = True
            elif self.use_custom_host and self.custom_host.strip():
                self.source_type = "standalone"

    def build_rtsp_url(
        self,
        nvr_host: str,
        nvr_rtsp_port: int,
        nvr_username: str,
        nvr_password: str,
        stream_type: str = "main",  # "main" or "sub"
        url_style: str = "isapi",
    ) -> str:
        """
        Construct the RTSP URL for this camera based on whether it uses the Primary NVR,
        a Secondary NVR, or a Standalone IP Camera / Custom RTSP URL.
        """
        if self.source_type == "primary_nvr" and not self.use_custom_host and not self.custom_rtsp_url.strip():
            target_ch = self.remote_channel_id if self.remote_channel_id > 0 else self.channel_id
            return format_rtsp_url_by_style(
                url_style=url_style,
                host=nvr_host,
                port=nvr_rtsp_port,
                username=nvr_username,
                password=nvr_password,
                channel_num=target_ch,
                stream_type=stream_type,
            )

        # Secondary NVR or Standalone Camera / Custom RTSP override
        host = self.custom_host.strip() or nvr_host.strip()
        port = self.custom_port if self.custom_port > 0 else nvr_rtsp_port
        user = self.custom_username.strip() if self.custom_username.strip() else nvr_username.strip()
        password = self.custom_password if self.custom_password else nvr_password
        style = self.custom_brand or url_style

        if self.source_type == "secondary_nvr":
            target_ch = self.remote_channel_id if self.remote_channel_id > 0 else 1
        else:
            target_ch = 1

        return format_rtsp_url_by_style(
            url_style=style,
            host=host,
            port=port,
            username=user,
            password=password,
            channel_num=target_ch,
            stream_type=stream_type,
            custom_main_url=self.custom_rtsp_url,
            custom_sub_url=self.custom_sub_rtsp_url,
        )


@dataclass
class AppConfig:
    """Top-level configuration for HikView."""
    device_model: str = "Hikvision / HiLook NVR"
    nvr_host: str = "192.168.1.64"
    nvr_rtsp_port: int = 554
    nvr_http_port: int = 80
    nvr_use_https: bool = False
    nvr_username: str = "admin"
    nvr_password: str = ""
    rtsp_transport: str = "tcp"  # "tcp" (recommended for reliability) or "udp"
    url_style: str = "isapi"     # "isapi", "legacy", "dahua", "reolink", "unv", "tp_link", "custom"
    default_layout: int = 4      # 1 (1x1), 4 (2x2), 13 (1+3), 6 (1+5), 9 (3x3), 16 (4x4)
    active_single_channel: int = 1
    auto_connect_on_startup: bool = False
    always_on_top: bool = False
    auto_substream_in_multi: bool = True  # Use sub-stream in multi-view and main-stream in single/primary view
    maintain_aspect_ratio: bool = True
    show_osd_overlay: bool = True
    reconnect_interval_sec: int = 5
    snapshot_dir: str = field(default_factory=lambda: str(get_snapshots_dir()))
    channels: List[CameraChannelConfig] = field(default_factory=list)
    # Maps the 16 viewport slots (0..15) in Grid layouts (2x2, 3x3, 4x4) to a camera channel_id or 0 (Empty Black View)
    slot_assignments: List[int] = field(default_factory=list)
    # Independent slot assignments (0..15) for Focus layouts (1+3, 1+5) where Slot 0 = Large Primary View
    focus_slot_assignments: List[int] = field(default_factory=list)

    def __post_init__(self):
        if not self.channels:
            self.channels = [
                CameraChannelConfig(channel_id=1, name="Camera 01 - Front", enabled=True),
                CameraChannelConfig(channel_id=2, name="Camera 02 - Side", enabled=True),
                CameraChannelConfig(channel_id=3, name="Camera 03 - Rear", enabled=True),
                CameraChannelConfig(channel_id=4, name="Camera 04 - Entrance", enabled=True),
            ]
        else:
            parsed = []
            for ch in self.channels:
                if isinstance(ch, dict):
                    # Filter only known fields so older/newer configs never fail
                    valid_keys = CameraChannelConfig.__dataclass_fields__.keys()
                    filtered = {k: v for k, v in ch.items() if k in valid_keys}
                    parsed.append(CameraChannelConfig(**filtered))
                else:
                    parsed.append(ch)
            self.channels = parsed

        # Ensure slot_assignments and focus_slot_assignments always have 16 slots (0..15)
        enabled_ids = [ch.channel_id for ch in self.channels if ch.enabled]
        if not self.slot_assignments:
            slots = enabled_ids + [0] * max(0, 16 - len(enabled_ids))
            self.slot_assignments = slots[:16]
        elif len(self.slot_assignments) < 16:
            existing = list(self.slot_assignments)
            used = {cid for cid in existing if cid > 0}
            for cid in enabled_ids:
                if cid not in used and len(existing) < 16:
                    existing.append(cid)
                    used.add(cid)
            while len(existing) < 16:
                existing.append(0)
            self.slot_assignments = existing[:16]

        if not self.focus_slot_assignments:
            self.focus_slot_assignments = list(self.slot_assignments[:16])
        elif len(self.focus_slot_assignments) < 16:
            existing_f = list(self.focus_slot_assignments)
            used_f = {cid for cid in existing_f if cid > 0}
            for cid in enabled_ids:
                if cid not in used_f and len(existing_f) < 16:
                    existing_f.append(cid)
                    used_f.add(cid)
            while len(existing_f) < 16:
                existing_f.append(0)
            self.focus_slot_assignments = existing_f[:16]

    def get_available_layouts(self) -> List[Tuple[str, int]]:
        """
        Return the list of (label, layout_code) choices dynamically tailored strictly to the number
        of ACTIVE (enabled) cameras:
        - Always includes the base 4-camera layouts: Single (1×1), Quad (2×2), Focus (1+3).
        - If 5 to 6 cameras are active (enabled): adds Focus (1+5).
        - If 7 to 9 cameras are active (enabled): adds Focus (1+5) and Grid (3×3).
        - If 10+ cameras are active (enabled): adds Focus (1+5), Grid (3×3), and Grid (4×4).
        """
        active_count = sum(1 for ch in self.channels if ch.enabled)

        layouts: List[Tuple[str, int]] = [
            ("Single (1×1)", 1),
            ("Quad (2×2)", 4),
            ("Focus (1+3)", 13),
        ]
        if active_count > 4:
            layouts.append(("Focus (1+5)", 6))
        if active_count > 6:
            layouts.append(("Grid (3×3)", 9))
        if active_count > 9:
            layouts.append(("Grid (4×4)", 16))
        return layouts

    def save(self, path: Optional[Path] = None) -> None:
        """
        Atomically save configuration to disk with automatic backup rotation.
        Writes to a temporary file first, flushes and syncs to disk, updates the
        backup file (.bak), and then performs an atomic replace so config.json is
        never corrupted or left empty even if the application is killed or powers down mid-write.
        """
        target = path or (get_config_dir() / "config.json")
        target_dir = target.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        backup = target.with_suffix(".json.bak")
        temp_file = target.with_name(f"{target.stem}.tmp.{os.getpid()}")

        data = asdict(self)
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

            # Before replacing target, if target exists and is non-empty, keep a backup
            if target.exists() and target.stat().st_size > 0:
                try:
                    shutil.copy2(target, backup)
                except Exception as bak_err:
                    logging.warning("Could not update config backup %s: %s", backup, bak_err)

            # Atomic replace (NTFS MoveFileExW with MOVEFILE_REPLACE_EXISTING)
            os.replace(temp_file, target)
        except Exception as e:
            logging.error("Failed to safely save configuration to %s: %s", target, e)
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            raise

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """
        Robustly load configuration from disk with automated recovery.
        If config.json is corrupted or empty:
          1. Preserves the damaged file as config.corrupt_<timestamp>.json for diagnostics.
          2. Recovers automatically from config.json.bak if available.
          3. Only falls back to factory defaults if no valid config or backup exists.
        """
        target = path or (get_config_dir() / "config.json")
        backup = target.with_suffix(".json.bak")

        def _try_parse(file_path: Path) -> Optional["AppConfig"]:
            if not file_path.exists() or file_path.stat().st_size == 0:
                return None
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return None
                valid_keys = cls.__dataclass_fields__.keys()
                filtered = {k: v for k, v in data.items() if k in valid_keys}
                return cls(**filtered)
            except Exception as parse_err:
                logging.error("Error reading configuration from %s: %s", file_path, parse_err)
                return None

        # Case 1: Primary configuration file exists
        if target.exists():
            cfg = _try_parse(target)
            if cfg is not None:
                # Valid config loaded. Ensure a backup exists as well.
                if not backup.exists() or backup.stat().st_size == 0:
                    try:
                        shutil.copy2(target, backup)
                    except Exception:
                        pass
                return cfg

            # Primary file exists but failed to parse (empty or corrupted)
            logging.critical("Primary configuration file at %s is corrupted or empty!", target)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt_dest = target.with_name(f"config.corrupt_{timestamp}.json")
            try:
                shutil.copy2(target, corrupt_dest)
                logging.info("Preserved corrupted configuration file to: %s", corrupt_dest)
            except Exception as preserve_err:
                logging.warning("Could not preserve corrupted configuration: %s", preserve_err)

            # Attempt recovery from backup file
            if backup.exists():
                logging.info("Attempting recovery from backup file: %s", backup)
                recovered_cfg = _try_parse(backup)
                if recovered_cfg is not None:
                    logging.info("Successfully recovered configuration from backup.")
                    setattr(recovered_cfg, "_recovered_from_backup", True)
                    try:
                        recovered_cfg.save(target)
                    except Exception as save_err:
                        logging.warning("Could not re-save recovered config to %s: %s", target, save_err)
                    return recovered_cfg

            # Both primary and backup failed
            logging.error("No valid backup found. Initializing factory defaults.")
            fallback_cfg = cls()
            setattr(fallback_cfg, "_corruption_detected", True)
            try:
                fallback_cfg.save(target)
            except Exception:
                pass
            return fallback_cfg

        # Case 2: Primary file does not exist, but backup exists
        if backup.exists():
            logging.info("Config file missing at %s, attempting restore from %s", target, backup)
            recovered_cfg = _try_parse(backup)
            if recovered_cfg is not None:
                setattr(recovered_cfg, "_recovered_from_backup", True)
                try:
                    recovered_cfg.save(target)
                except Exception:
                    pass
                return recovered_cfg

        # Case 3: Fresh install or no previous config
        logging.info("No configuration found at %s. Creating initial defaults.", target)
        new_cfg = cls()
        try:
            new_cfg.save(target)
        except Exception as init_err:
            logging.warning("Could not save initial configuration: %s", init_err)
        return new_cfg
