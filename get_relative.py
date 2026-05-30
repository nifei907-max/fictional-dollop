import pyautogui
import win32gui
import win32con

# 1. 找到交易软件窗口
title_keyword = "华中九通"
hwnd = None

def find_window(hwnd, _):
    global hwnd_found
    if win32gui.IsWindowVisible(hwnd) and title_keyword in win32gui.GetWindowText(hwnd):
        hwnd_found = hwnd

hwnd_found = None
win32gui.EnumWindows(find_window, None)

if hwnd_found is None:
    print("❌ 未找到包含“华中九通”的窗口，请确保交易软件已打开。")
    exit()

# 2. 获取窗口客户区左上角的屏幕坐标
client_rect = win32gui.GetClientRect(hwnd_found)
left_top = win32gui.ClientToScreen(hwnd_found, (0, 0))
print(f"窗口客户区左上角屏幕坐标: {left_top}")

# 3. 提示用户移动鼠标到价格数字左上角
print("请将鼠标移动到「实时价格数字」的左上角，然后按 Enter...")
input()
mx, my = pyautogui.position()
print(f"鼠标当前位置: ({mx}, {my})")

# 4. 计算相对偏移
rel_left = mx - left_top[0]
rel_top = my - left_top[1]
print(f"\n✅ 测量完成！")
print(f"rel_left = {rel_left}")
print(f"rel_top = {rel_top}")
print("请将这两个数字填入 user_config.json 的 capture 区域中的 rel_left 和 rel_top。")