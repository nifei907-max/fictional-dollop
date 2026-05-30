import win32gui
import win32con
import win32api          # 修复：GetSystemMetrics 在这个模块里

TITLE = "华中九通"
WIDTH = 969
HEIGHT = 370

def find_window_by_title(title):
    hwnd = win32gui.FindWindow(None, None)
    while hwnd:
        if win32gui.IsWindowVisible(hwnd):
            win_title = win32gui.GetWindowText(hwnd)
            if title in win_title:
                return hwnd
        hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)
    return None

hwnd = find_window_by_title(TITLE)
if hwnd is None:
    print(f"未找到包含 '{TITLE}' 的窗口，请确保交易软件已打开。")
    input("按 Enter 退出...")
    exit()

# 获取屏幕宽度，计算右上角坐标
screen_width = win32api.GetSystemMetrics(0)   # 这里改成 win32api
x = screen_width - WIDTH
y = 0

# 设置窗口位置和大小，并置顶
win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, WIDTH, HEIGHT,
                      win32con.SWP_SHOWWINDOW)

print(f"窗口已固定在右上角 ({x}, {y})，大小 {WIDTH}x{HEIGHT}，并置顶。")
print("现在其他程序无法遮挡它。")
input("按 Enter 退出...")