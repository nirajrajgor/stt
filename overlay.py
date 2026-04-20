"""Floating waveform indicator shown while recording.

Cocoa must own the main thread, so `run_forever()` blocks there. Audio and
hotkey threads push amplitudes and toggle visibility via the public helpers;
any call that touches Cocoa is marshaled onto the main operation queue.
"""

import signal
import threading
import traceback
from collections import deque

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSEventTypeApplicationDefined,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import (
    NSMakePoint,
    NSMakeRect,
    NSObject,
    NSOperationQueue,
    NSTimer,
)

WINDOW_WIDTH = 240.0
WINDOW_HEIGHT = 48.0
BOTTOM_MARGIN = 60.0
BAR_COUNT = 30
BAR_WIDTH = 3.0
BAR_GAP = 3.0
CORNER_RADIUS = 20.0
REDRAW_HZ = 30.0
# RMS of normal speech lands around 0.02–0.15; this scales it to fill the pill.
AMPLITUDE_SCALE = 8.0

_app = None
_window = None
_view = None
_timer = None
_timer_target = None

_amp_lock = threading.Lock()
_amplitudes = deque([0.0] * BAR_COUNT, maxlen=BAR_COUNT)


class WaveformView(NSView):
    def drawRect_(self, rect):
        # Any exception escaping drawRect_ becomes an NSException, which abort()s
        # NSApp.run() (SIGTRAP). Contain it.
        try:
            self._draw()
        except Exception:
            traceback.print_exc()

    def _draw(self):
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height

        bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, CORNER_RADIUS, CORNER_RADIUS
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.72).set()
        bg.fill()

        total_w = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP
        start_x = (w - total_w) / 2.0
        center_y = h / 2.0
        min_h = 3.0
        max_h = h - 14.0

        # Snapshot under the lock — iterating the live deque while the audio
        # thread appends raises "deque mutated during iteration".
        with _amp_lock:
            amps = list(_amplitudes)

        NSColor.whiteColor().set()
        for i, a in enumerate(amps):
            scaled = min(1.0, a * AMPLITUDE_SCALE)
            bh = min_h + scaled * (max_h - min_h)
            x = start_x + i * (BAR_WIDTH + BAR_GAP)
            y = center_y - bh / 2.0
            bar = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, BAR_WIDTH, bh),
                BAR_WIDTH / 2.0,
                BAR_WIDTH / 2.0,
            )
            bar.fill()


class _TimerTarget(NSObject):
    """NSTimer target. Target/selector is more robust across pyobjc versions
    than the block-based scheduledTimer variant."""

    def redraw_(self, timer):
        if _view is not None:
            _view.setNeedsDisplay_(True)

    def tickle_(self, timer):
        # Fires periodically so Python can process deferred signal handlers
        # while NSApp.run() is parked in C.
        pass


def _stop_app():
    """Break out of NSApp.run() and wake it with a dummy event so it returns."""
    try:
        _app.stop_(None)
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            NSEventTypeApplicationDefined, NSMakePoint(0, 0), 0, 0.0, 0, None, 0, 0, 0
        )
        _app.postEvent_atStart_(ev, True)
    except Exception:
        traceback.print_exc()


def _run_on_main(block):
    NSOperationQueue.mainQueue().addOperationWithBlock_(block)


def _position_window():
    """Place the pill bottom-center on whichever display contains the mouse."""
    mouse = NSEvent.mouseLocation()
    screen = None
    for s in NSScreen.screens():
        f = s.frame()
        if (f.origin.x <= mouse.x <= f.origin.x + f.size.width
                and f.origin.y <= mouse.y <= f.origin.y + f.size.height):
            screen = s
            break
    if screen is None:
        screen = NSScreen.mainScreen()
    vf = screen.visibleFrame()
    x = vf.origin.x + (vf.size.width - WINDOW_WIDTH) / 2.0
    y = vf.origin.y + BOTTOM_MARGIN
    _window.setFrame_display_(NSMakeRect(x, y, WINDOW_WIDTH, WINDOW_HEIGHT), True)


def _start_timer():
    global _timer
    if _timer is not None:
        return
    _timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.0 / REDRAW_HZ, _timer_target, "redraw:", None, True
    )


def _stop_timer():
    global _timer
    if _timer is not None:
        _timer.invalidate()
        _timer = None


def start():
    """Create NSApp and the overlay window. Must run on the main thread."""
    global _app, _window, _view, _timer_target

    _app = NSApplication.sharedApplication()
    _app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    _timer_target = _TimerTarget.alloc().init()

    rect = NSMakeRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT)
    # NSPanel + NonactivatingPanel is the canonical floating-HUD recipe: the
    # window appears without making this process the active app, so simulated
    # Cmd+V in stop_recording still lands in whatever had focus before.
    _window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect,
        NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered,
        False,
    )
    _window.setOpaque_(False)
    _window.setBackgroundColor_(NSColor.clearColor())
    _window.setHasShadow_(False)
    _window.setLevel_(NSStatusWindowLevel)
    _window.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorFullScreenAuxiliary
        | NSWindowCollectionBehaviorStationary
    )
    _window.setIgnoresMouseEvents_(True)

    _view = WaveformView.alloc().initWithFrame_(rect)
    _window.setContentView_(_view)


def run_forever():
    """Run the Cocoa event loop. Blocks until Ctrl+C / NSApp.stop_()."""
    def _sigint(signum, frame):
        _run_on_main(_stop_app)

    signal.signal(signal.SIGINT, _sigint)
    # Periodic no-op so Python can service deferred signal handlers during run().
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.25, _timer_target, "tickle:", None, True
    )
    _app.run()


def show():
    """Show the overlay. Safe from any thread."""
    def _do():
        with _amp_lock:
            _amplitudes.clear()
            _amplitudes.extend([0.0] * BAR_COUNT)
        _position_window()
        _window.orderFrontRegardless()
        _start_timer()
    _run_on_main(_do)


def hide():
    """Hide the overlay. Safe from any thread."""
    def _do():
        _stop_timer()
        _window.orderOut_(None)
    _run_on_main(_do)


def stop():
    """Stop the Cocoa event loop. Safe from any thread."""
    _run_on_main(_stop_app)


def push_amplitude(level):
    """Append an RMS sample into the rolling buffer. Safe from any thread."""
    with _amp_lock:
        _amplitudes.append(level)
