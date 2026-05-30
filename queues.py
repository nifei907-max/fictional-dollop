"""消息队列定义"""
from queue import Queue

tick_queue = Queue(maxsize=5000)      # (price, tick_time)
candle_queue = Queue(maxsize=500)     # finished candle dict
signal_queue = Queue(maxsize=50)      # signal dict or None