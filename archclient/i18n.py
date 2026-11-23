# -*- coding: utf-8 -*-
"""Chuỗi giao diện Việt / Anh + nhận diện ngôn ngữ."""
from __future__ import annotations

import os

STRINGS = {
    "vi": {
        # --- điều hướng
        "nav_home": "Tổng quan", "nav_files": "Thư mục", "nav_mods": "Mods",
        "nav_optimize": "Tối ưu", "nav_console": "Console", "nav_settings": "Cài đặt",
        "nav_website": "Website",
        "sub_home": "Minecraft {ver} · Fabric", "sub_files": "Nội dung trong .minecraft",
        "sub_mods": "Tìm và tải từ Modrinth", "sub_optimize": "Mod hiệu năng và tinh chỉnh Linux",
        "sub_console": "Nhật ký launcher và game", "sub_settings": "Tuỳ chỉnh launcher",
        # --- trạng thái
        "st_ready": "Sẵn sàng", "st_busy": "Đang xử lý", "st_error": "Lỗi", "st_playing": "Đang chơi",
        "btn_play": "Chơi ngay", "btn_playing": "Đang chơi", "btn_install_loader": "Cài {loader}", "btn_install_vanilla": "Tải bản gốc",
        # --- tổng quan
        "hero_title": "Sẵn sàng vào game?",
        "hero_sub": "Minecraft {ver} với {loader}. Mọi thứ được cài sẵn khi bạn bấm chơi.",
        "ver_label": "Phiên bản Minecraft", "loader_label": "Loader",
        "card_java": "Java", "card_ram": "Bộ nhớ cấp cho game", "card_system": "Hệ thống",
        "java_unchecked": "Chưa kiểm tra", "java_checking": "Đang kiểm tra…",
        "java_ok": "Java {v} sẵn sàng", "java_installing": "Đang cài Java…",
        "java_fail": "Cài Java thất bại", "java_missing": "Chưa có Java",
        "java_old": "Java {v} quá cũ (cần {need}+)",
        "ram_of": "{used} / {total} GB RAM máy", "ram_suggest": "Gợi ý {n} GB",
        "sys_line": "{gpu} · {session}", "sys_cpu": "{cores} nhân · {gov}",
        "installed_title": "Đã cài", "cat_mods": "Mods", "cat_resourcepacks": "Resource Packs",
        "cat_shaderpacks": "Shaders", "cat_schematics": "Schematics",
        # --- thư mục
        "files_dir": "Thư mục .minecraft", "btn_change_dir": "Đổi thư mục", "btn_open_dir": "Mở thư mục",
        "btn_refresh": "Làm mới", "btn_delete": "Xoá mục đã chọn", "files_empty": "Chưa có tệp nào ở đây.",
        "files_count": "{n} mục", "delete_title": "Xoá {n} mục?",
        "delete_body": "Các tệp sẽ bị xoá vĩnh viễn khỏi ổ đĩa.", "btn_cancel": "Huỷ", "btn_confirm": "Xoá",
        "deleted": "Đã xoá {n} mục",
        # --- mods
        "search_ph": "Tìm kiếm trên Modrinth…", "type_mod": "Mods", "type_resourcepack": "Resource Packs",
        "type_shader": "Shaders", "btn_download": "Tải", "btn_open_page": "Trang web",
        "btn_load_more": "Tải thêm", "mods_searching": "Đang tìm…",
        "mods_found": "{n} kết quả cho Minecraft {ver}", "mods_empty": "Không có kết quả cho Minecraft {ver}",
        "mods_error": "Không tìm được: {err}", "mods_downloading": "Đang tải {name}…",
        "mods_done": "Đã tải {name}", "mods_fail": "{name}: không có bản cho Minecraft {ver}",
        "mods_offline": "Không có kết nối tới Modrinth.", "downloads": "{n} lượt tải", "btn_retry": "Thử lại",
        # --- tối ưu
        "opt_mods_title": "Mod hiệu năng", "opt_mods_sub": "Tải bản khớp đúng phiên bản Minecraft và loader của bạn", "opt_vanilla": "Bản Vanilla không có mod — chọn Fabric, Quilt, Forge hoặc NeoForge ở trang chủ.",
        "opt_apply": "Áp dụng tối ưu", "opt_running": "Đang tối ưu…", "opt_done": "Tối ưu hoàn tất",
        "lin_title": "Tinh chỉnh Linux", "lin_sub": "Chỉ có trên bản Linux. Mỗi tuỳ chọn được lưu ngay.",
        "btn_rescan": "Quét lại phần cứng", "btn_install_tools": "Cài gamemode / MangoHud",
        "missing_cmd": "chưa cài {cmd}", "lin_saved": "Đã lưu tuỳ chọn Linux",
        "mod_sodium": "Engine render siêu nhanh, nền tảng cho FPS cao",
        "mod_lithium": "Tối ưu logic game, giảm tick lag",
        "mod_starlight": "Tối ưu ánh sáng, giảm lag chunk",
        "mod_ferrite-core": "Giảm lượng RAM sử dụng",
        "mod_krypton": "Tối ưu mạng, đỡ lag khi chơi server",
        "mod_lazydfu": "Game khởi động nhanh hơn",
        "mod_iris": "Hỗ trợ shader, tương thích Sodium",
        "mod_modernfix": "Giảm RAM và tăng tốc khởi động",
        "mod_entityculling": "Bỏ render entity ngoài tầm nhìn",
        "mod_immediatelyfast": "Tăng tốc vẽ giao diện",
        "mod_embeddium": "Engine render kiểu Sodium cho Forge / NeoForge",
        "mod_badoptimizations": "Tối ưu nhỏ nhưng hiệu quả, giảm lag",
        "mod_sodium-options-api": "Thư viện tuỳ chọn cho Embeddium",
        "tw_gamemode": "gamemoderun", "tw_gamemode_d": "Ép CPU và GPU vào chế độ hiệu năng khi chơi",
        "tw_mangohud": "MangoHud", "tw_mangohud_d": "Hiện FPS và nhiệt độ ngay trong game",
        "tw_glthread": "Threaded OpenGL", "tw_glthread_d": "Mesa và NVIDIA, thường tăng 5–20% FPS",
        "tw_shader_cache": "Cache shader", "tw_shader_cache_d": "Vào game và tải chunk nhanh hơn từ lần chạy thứ hai",
        "tw_allocator": "jemalloc / mimalloc", "tw_allocator_d": "JVM bớt phình RAM, bớt giật khựng",
        "tw_thp": "Huge Pages + NUMA", "tw_thp_d": "Giảm giật khi dọn rác bộ nhớ (GC)",
        "tw_dgpu": "Dùng GPU rời", "tw_dgpu_d": "Cho laptop có hai GPU",
        "tw_no_vsync": "Tắt VSync ở driver", "tw_no_vsync_d": "Giảm input lag",
        "tw_wm_fix": "Sửa cửa sổ trống", "tw_wm_fix_d": "Cho i3, sway, bspwm",
        "tw_system_glfw": "GLFW của hệ thống", "tw_system_glfw_d": "Chạy Wayland mượt hơn",
        "tw_high_priority": "Ưu tiên CPU cao", "tw_high_priority_d": "Chạy với nice -5",
        "tw_zgc": "ZGC thay G1", "tw_zgc_d": "Chỉ có tác dụng khi cấp từ 8 GB RAM",
        # --- console
        "btn_clear": "Xoá", "btn_save_log": "Lưu .txt", "btn_copy": "Sao chép", "btn_open_logs": "Thư mục lỗi",
        "log_saved": "Đã lưu: {path}", "log_copied": "Đã sao chép console",
        # --- cài đặt
        "set_general": "Chung", "set_language": "Ngôn ngữ", "lang_auto": "Tự động", "lang_vi": "Tiếng Việt",
        "lang_en": "English", "set_version": "Phiên bản Minecraft",
        "set_java": "Java", "set_java_path": "Đường dẫn Java", "btn_browse": "Chọn…",
        "set_java_target": "Bản Java sẽ cài", "btn_install_java": "Kiểm tra / cài Java",
        "set_memory": "Bộ nhớ", "set_ram": "RAM cấp cho game",
        "ram_hint": "Tối đa 75% RAM máy để tránh bị hệ điều hành đóng game. Gợi ý: {n} GB.",
        "set_account": "Tài khoản", "set_username": "Tên người chơi", "set_client_id": "Azure client_id",
        "btn_login": "Thêm tài khoản Microsoft", "login_ok": "Đã đăng nhập: {name}",
        "login_need_id": "Hãy điền Azure client_id trước", "login_title": "Đăng nhập Microsoft",
        "login_body": "Trình duyệt đã mở trang đăng nhập. Sau khi đăng nhập, sao chép địa chỉ (URL) cuối cùng của trang và dán vào đây.",
        "login_ph": "https://login.microsoftonline.com/…", "btn_ok": "Xác nhận",
        "login_body_auto": "Trình duyệt đã mở trang đăng nhập Microsoft. Đăng nhập xong sẽ tự quay lại launcher. Lần đầu cần thêm http://localhost vào Redirect URI của Azure app.",
        "btn_paste_url": "Dán URL thủ công", "btn_logout": "Đăng xuất", "logout_ok": "Đã đăng xuất",
        "login_timeout": "Hết thời gian chờ đăng nhập", "login_no_game": "Tài khoản này chưa sở hữu Minecraft Java",
        "login_app_denied": "Azure app chưa được Microsoft cho phép dùng Minecraft API",
        "login_failed": "Đăng nhập thất bại: {err}",
        "login_page_ok": "Đăng nhập xong", "login_page_err": "Đăng nhập không thành công",
        "login_page_hint": "Bạn có thể đóng tab này và quay lại Arch Client.",
        "set_interface": "Giao diện", "set_sound": "Âm thanh giao diện", "set_volume": "Âm lượng",
        "set_glass": "Độ trong của kính", "set_bg_anim": "Nền chuyển động nhẹ",
        "set_minimize": "Thu nhỏ launcher khi vào game", "set_restart_hint": "Áp dụng sau khi mở lại launcher",
        "set_shortcut": "Shortcut", "sc_installed": "Đã cài trong menu ứng dụng và Desktop",
        "sc_missing": "Chưa có shortcut", "btn_sc_install": "Cài shortcut", "btn_sc_remove": "Gỡ shortcut",
        "saved": "Đã lưu cài đặt",
        # --- thông báo / log
        "lang_changed": "Đã đổi ngôn ngữ", "ver_changed": "Đã chọn Minecraft {ver}", "loader_changed": "Đã chọn {loader}",
        "need_fabric": "Chưa cài loader cho phiên bản này", "need_java": "Chưa có Java hợp lệ",
        "game_started": "Game đang chạy", "game_closed": "Game đã đóng", "game_crash": "Game thoát với mã lỗi {code}",
        "fabric_ok": "Đã cài Fabric", "loader_ok": "Đã cài {loader}", "loader_failed": "Cài {loader} thất bại, xem Console", "loader_unsupported": "{loader} chưa hỗ trợ Minecraft {ver}", "mll_old": "Cần minecraft-launcher-lib >= 8.0", "java_lazy": "Cần Java — tự cài khi chơi", "mods_vanilla": "Vanilla không dùng mod. Chọn loader khác ở trang chủ.", "set_ver_kind": "Loại phiên bản", "ver_kind_d": "Hiện thêm snapshot, beta, alpha trong danh sách", "set_isolate": "Tách thư mục theo loader", "set_isolate_d": "Mỗi loader và phiên bản có mods, saves, config riêng", "btn_add_file": "Thêm file…", "added_n": "Đã thêm {n} file", "kind_release": "Release", "kind_snapshot": "+ Snapshot", "kind_all": "Tất cả", "busy_wait": "Đang có một tác vụ khác, đợi chút",
        "acc_ms": "Microsoft", "acc_offline": "Offline", "acc_label": "Tài khoản",
        "acc_bad_name": "Tên cần 3–16 ký tự chữ, số hoặc _", "acc_dup": "{name} đang chạy rồi — server sẽ đá tài khoản trùng",
        "acc_expired": "Phiên đăng nhập của {name} đã hết hạn, hãy đăng nhập lại", "acc_refresh_fail": "Không làm mới được {name}: {err}",
        "low_ram_multi": "RAM trống chỉ còn {avail} MB, game mới cần {need} MB — có thể bị đơ máy",
        "st_playing_n": "Đang chơi ×{n}", "btn_play_another": "Mở thêm game",
        "acc_add_offline": "Thêm tài khoản offline", "acc_add_offline_d": "Chỉ cần một cái tên, không cần đăng nhập",
        "acc_name_ph": "Tên người chơi", "btn_add": "Thêm", "acc_use": "Dùng", "acc_active": "Đang chọn",
        "acc_relogin": "Cần đăng nhập lại", "acc_remove": "Xoá tài khoản",
        "splash_start": "Đang khởi động…", "splash_lang": "Nhận diện ngôn ngữ…", "splash_ui": "Dựng giao diện…",
        "already_running": "Arch Client đang chạy rồi.",
        "close": "Đóng", "minimize": "Thu nhỏ", "maximize": "Phóng to",
    },
    "en": {
        "nav_home": "Home", "nav_files": "Files", "nav_mods": "Mods",
        "nav_optimize": "Optimize", "nav_console": "Console", "nav_settings": "Settings",
        "nav_website": "Website",
        "sub_home": "Minecraft {ver} · Fabric", "sub_files": "Contents of .minecraft",
        "sub_mods": "Search and download from Modrinth", "sub_optimize": "Performance mods and Linux tuning",
        "sub_console": "Launcher and game log", "sub_settings": "Customize the launcher",
        "st_ready": "Ready", "st_busy": "Working", "st_error": "Error", "st_playing": "Playing",
        "btn_play": "Play now", "btn_playing": "Playing", "btn_install_loader": "Install {loader}", "btn_install_vanilla": "Download vanilla",
        "hero_title": "Ready to play?",
        "hero_sub": "Minecraft {ver} with {loader}. Everything installs itself when you hit play.",
        "ver_label": "Minecraft version", "loader_label": "Loader",
        "card_java": "Java", "card_ram": "Memory for the game", "card_system": "System",
        "java_unchecked": "Not checked yet", "java_checking": "Checking…",
        "java_ok": "Java {v} ready", "java_installing": "Installing Java…",
        "java_fail": "Java install failed", "java_missing": "Java not found",
        "java_old": "Java {v} is too old (need {need}+)",
        "ram_of": "{used} / {total} GB system RAM", "ram_suggest": "Suggested {n} GB",
        "sys_line": "{gpu} · {session}", "sys_cpu": "{cores} cores · {gov}",
        "installed_title": "Installed", "cat_mods": "Mods", "cat_resourcepacks": "Resource Packs",
        "cat_shaderpacks": "Shaders", "cat_schematics": "Schematics",
        "files_dir": ".minecraft folder", "btn_change_dir": "Change folder", "btn_open_dir": "Open folder",
        "btn_refresh": "Refresh", "btn_delete": "Delete selected", "files_empty": "Nothing here yet.",
        "files_count": "{n} items", "delete_title": "Delete {n} items?",
        "delete_body": "These files will be permanently removed from disk.", "btn_cancel": "Cancel",
        "btn_confirm": "Delete", "deleted": "Deleted {n} items",
        "search_ph": "Search on Modrinth…", "type_mod": "Mods", "type_resourcepack": "Resource Packs",
        "type_shader": "Shaders", "btn_download": "Download", "btn_open_page": "Web page",
        "btn_load_more": "Load more", "mods_searching": "Searching…",
        "mods_found": "{n} results for Minecraft {ver}", "mods_empty": "No results for Minecraft {ver}",
        "mods_error": "Search failed: {err}", "mods_downloading": "Downloading {name}…",
        "mods_done": "Downloaded {name}", "mods_fail": "{name}: no build for Minecraft {ver}",
        "mods_offline": "Can't reach Modrinth.", "downloads": "{n} downloads", "btn_retry": "Retry",
        "opt_mods_title": "Performance mods", "opt_mods_sub": "Downloads builds matching your Minecraft version and loader", "opt_vanilla": "Vanilla has no mods — pick Fabric, Quilt, Forge or NeoForge on the home page.",
        "opt_apply": "Apply optimization", "opt_running": "Optimizing…", "opt_done": "Optimization complete",
        "lin_title": "Linux tuning", "lin_sub": "Linux only. Every option saves instantly.",
        "btn_rescan": "Rescan hardware", "btn_install_tools": "Install gamemode / MangoHud",
        "missing_cmd": "{cmd} not installed", "lin_saved": "Linux options saved",
        "mod_sodium": "Blazing-fast render engine, the base of high FPS",
        "mod_lithium": "Optimizes game logic, cuts tick lag",
        "mod_starlight": "Rewrites lighting, removes chunk lag",
        "mod_ferrite-core": "Lowers memory usage",
        "mod_krypton": "Network optimizations for servers",
        "mod_lazydfu": "Faster game startup",
        "mod_iris": "Shader support, works with Sodium",
        "mod_modernfix": "Less RAM and faster startup",
        "mod_entityculling": "Skips rendering unseen entities",
        "mod_immediatelyfast": "Speeds up UI rendering",
        "mod_embeddium": "Sodium-style render engine for Forge / NeoForge",
        "mod_badoptimizations": "Small but effective optimizations",
        "mod_sodium-options-api": "Options library for Embeddium",
        "tw_gamemode": "gamemoderun", "tw_gamemode_d": "Forces CPU and GPU into performance mode",
        "tw_mangohud": "MangoHud", "tw_mangohud_d": "In-game FPS and temperature overlay",
        "tw_glthread": "Threaded OpenGL", "tw_glthread_d": "Mesa and NVIDIA, usually 5–20% more FPS",
        "tw_shader_cache": "Shader cache", "tw_shader_cache_d": "Faster startup and chunk loading from the 2nd run",
        "tw_allocator": "jemalloc / mimalloc", "tw_allocator_d": "Less JVM memory bloat and fewer stutters",
        "tw_thp": "Huge Pages + NUMA", "tw_thp_d": "Smoother garbage collection",
        "tw_dgpu": "Use discrete GPU", "tw_dgpu_d": "For hybrid-GPU laptops",
        "tw_no_vsync": "Disable driver VSync", "tw_no_vsync_d": "Lower input lag",
        "tw_wm_fix": "Fix blank window", "tw_wm_fix_d": "For i3, sway, bspwm",
        "tw_system_glfw": "System GLFW", "tw_system_glfw_d": "Smoother on Wayland",
        "tw_high_priority": "High CPU priority", "tw_high_priority_d": "Runs with nice -5",
        "tw_zgc": "ZGC instead of G1", "tw_zgc_d": "Only helps with 8 GB+ allocated",
        "btn_clear": "Clear", "btn_save_log": "Save .txt", "btn_copy": "Copy", "btn_open_logs": "Error logs",
        "log_saved": "Saved: {path}", "log_copied": "Console copied",
        "set_general": "General", "set_language": "Language", "lang_auto": "Auto", "lang_vi": "Tiếng Việt",
        "lang_en": "English", "set_version": "Minecraft version",
        "set_java": "Java", "set_java_path": "Java path", "btn_browse": "Browse…",
        "set_java_target": "Java version to install", "btn_install_java": "Check / install Java",
        "set_memory": "Memory", "set_ram": "RAM for the game",
        "ram_hint": "Capped at 75% of system RAM so the OS never kills the game. Suggested: {n} GB.",
        "set_account": "Account", "set_username": "Player name", "set_client_id": "Azure client_id",
        "btn_login": "Add Microsoft account", "login_ok": "Signed in as {name}",
        "login_need_id": "Enter your Azure client_id first", "login_title": "Microsoft sign-in",
        "login_body": "Your browser opened the sign-in page. After signing in, copy the final page address (URL) and paste it here.",
        "login_ph": "https://login.microsoftonline.com/…", "btn_ok": "Confirm",
        "login_body_auto": "Your browser opened the Microsoft sign-in page. After signing in you will return to the launcher automatically. First time only: add http://localhost to your Azure app's Redirect URIs.",
        "btn_paste_url": "Paste URL manually", "btn_logout": "Sign out", "logout_ok": "Signed out",
        "login_timeout": "Sign-in timed out", "login_no_game": "This account does not own Minecraft Java",
        "login_app_denied": "This Azure app is not approved by Microsoft for the Minecraft API",
        "login_failed": "Sign-in failed: {err}",
        "login_page_ok": "Signed in", "login_page_err": "Sign-in failed",
        "login_page_hint": "You can close this tab and go back to Arch Client.",
        "set_interface": "Interface", "set_sound": "Interface sounds", "set_volume": "Volume",
        "set_glass": "Glass opacity", "set_bg_anim": "Gentle moving background",
        "set_minimize": "Minimize launcher when the game starts", "set_restart_hint": "Applies after restarting the launcher",
        "set_shortcut": "Shortcut", "sc_installed": "Installed in the app menu and on the Desktop",
        "sc_missing": "No shortcut yet", "btn_sc_install": "Install shortcut", "btn_sc_remove": "Remove shortcut",
        "saved": "Settings saved",
        "lang_changed": "Language changed", "ver_changed": "Minecraft {ver} selected", "loader_changed": "{loader} selected",
        "need_fabric": "No loader installed for this version", "need_java": "No valid Java found",
        "game_started": "Game is running", "game_closed": "Game closed", "game_crash": "Game exited with code {code}",
        "fabric_ok": "Fabric installed", "loader_ok": "{loader} installed", "loader_failed": "{loader} install failed, see Console", "loader_unsupported": "{loader} does not support Minecraft {ver}", "mll_old": "Needs minecraft-launcher-lib >= 8.0", "java_lazy": "Java needed — installs when you play", "mods_vanilla": "Vanilla has no mods. Pick another loader on the home page.", "set_ver_kind": "Version type", "ver_kind_d": "Also list snapshots, beta and alpha builds", "set_isolate": "Separate folder per loader", "set_isolate_d": "Each loader and version gets its own mods, saves and config", "btn_add_file": "Add files…", "added_n": "Added {n} file(s)", "kind_release": "Release", "kind_snapshot": "+ Snapshot", "kind_all": "All", "busy_wait": "Another task is running, hold on",
        "acc_ms": "Microsoft", "acc_offline": "Offline", "acc_label": "Account",
        "acc_bad_name": "Name needs 3–16 letters, digits or _", "acc_dup": "{name} is already running — servers kick duplicate accounts",
        "acc_expired": "{name}'s sign-in has expired, please sign in again", "acc_refresh_fail": "Could not refresh {name}: {err}",
        "low_ram_multi": "Only {avail} MB RAM free, the new game needs {need} MB — the system may freeze",
        "st_playing_n": "Playing ×{n}", "btn_play_another": "Launch another",
        "acc_add_offline": "Add offline account", "acc_add_offline_d": "Just a name, no sign-in needed",
        "acc_name_ph": "Player name", "btn_add": "Add", "acc_use": "Use", "acc_active": "In use",
        "acc_relogin": "Sign in again", "acc_remove": "Remove account",
        "splash_start": "Starting…", "splash_lang": "Detecting language…", "splash_ui": "Building interface…",
        "already_running": "Arch Client is already running.",
        "close": "Close", "minimize": "Minimize", "maximize": "Maximize",
    },
}


# Chuỗi riêng cho Windows: ghi đè các chuỗi nói về Linux, thêm tên các tuỳ chọn Windows.
WINDOWS_STRINGS = {
    "vi": {
        "sub_optimize": "Mod hiệu năng và tinh chỉnh Windows",
        "lin_title": "Tinh chỉnh Windows",
        "lin_sub": "Chỉ có trên bản Windows. Không cần quyền admin, tắt công tắc là trả lại như cũ.",
        "lin_saved": "Đã lưu tuỳ chọn Windows",
        "sc_installed": "Đã tạo trong Start Menu và Desktop",
        "tw_gpu_pref": "GPU hiệu năng cao", "tw_gpu_pref_d": "Ép Java chạy trên GPU rời (laptop có hai GPU)",
        "tw_win_gamemode": "Game Mode", "tw_win_gamemode_d": "Windows dành tài nguyên cho game đang chạy",
        "tw_win_priority": "Ưu tiên CPU cao hơn", "tw_win_priority_d": "Game được xếp trước các tiến trình nền",
        "tw_power_plan": "Power plan hiệu năng cao", "tw_power_plan_d": "Chỉ trong lúc chơi, thoát game là trả lại",
        "tw_disable_dvr": "Tắt Game DVR", "tw_disable_dvr_d": "Ngừng quay nền của Xbox Game Bar, bớt giật",
        "tw_disable_fso": "Tắt Fullscreen Optimizations", "tw_disable_fso_d": "Giảm input lag ở toàn màn hình",
    },
    "en": {
        "sub_optimize": "Performance mods and Windows tuning",
        "lin_title": "Windows tuning",
        "lin_sub": "Windows only. No admin rights needed, switch off to undo.",
        "lin_saved": "Windows options saved",
        "sc_installed": "Created in the Start Menu and on the Desktop",
        "tw_gpu_pref": "High-performance GPU", "tw_gpu_pref_d": "Forces Java onto the discrete GPU (hybrid laptops)",
        "tw_win_gamemode": "Game Mode", "tw_win_gamemode_d": "Windows prioritises the running game",
        "tw_win_priority": "Higher CPU priority", "tw_win_priority_d": "Game is scheduled ahead of background tasks",
        "tw_power_plan": "High-performance power plan", "tw_power_plan_d": "Only while playing, restored on exit",
        "tw_disable_dvr": "Disable Game DVR", "tw_disable_dvr_d": "Stops Xbox Game Bar background capture",
        "tw_disable_fso": "Disable Fullscreen Optimizations", "tw_disable_fso_d": "Lower input lag in fullscreen",
    },
}


def apply_platform_strings(is_windows: bool) -> None:
    """Gộp chuỗi riêng của Windows vào bảng chính (gọi một lần lúc import)."""
    if is_windows:
        for lang, extra in WINDOWS_STRINGS.items():
            STRINGS[lang].update(extra)


def tr(lang: str, key: str, **kw) -> str:
    s = STRINGS.get(lang, {}).get(key)
    if s is None:
        s = STRINGS["en"].get(key, key)
    if kw:
        try:
            return s.format(**kw)
        except Exception:
            return s
    return s


def _locale_is_vi() -> bool:
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        v = (os.environ.get(var) or "").lower()
        if v:
            return v.startswith("vi")
    try:
        import locale
        loc = (locale.getlocale()[0] or "").lower()
        return loc.startswith("vi")
    except Exception:
        return False


def detect_language(requests_mod=None, timeout=2.5) -> str:
    """'vi' nếu locale hệ thống là tiếng Việt hoặc IP ở Việt Nam, ngược lại 'en'."""
    if _locale_is_vi():
        return "vi"
    if requests_mod is not None:
        for url in ("https://ipapi.co/json/", "https://ipwho.is/"):
            try:
                r = requests_mod.get(url, timeout=timeout)
                r.raise_for_status()
                d = r.json()
                cc = (d.get("country_code") or d.get("country") or "").upper()
                if cc:
                    return "vi" if cc == "VN" else "en"
            except Exception:
                continue
    return "en"


from .bootstrap import IS_WINDOWS as _IS_WINDOWS  # noqa: E402

apply_platform_strings(_IS_WINDOWS)
