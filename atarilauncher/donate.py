"""The optional "Support Code" button. Code is free; this only opens the donate page in the web browser when the person presses it.
No pop-ups, no reminders, nothing is ever shown unless the button is pressed. To change where it points (another PayPal.me link, a
different page), change DONATE_URL here - it is the only place the address is written."""

DONATE_URL = "https://paypal.me/Codeemulator"

TITLE = "Support Code (optional)"
DETAIL = ("Code is free and always will be. If you like it, you can chip in through PayPal - this opens the donate page in the web browser. "
          "Totally optional; Code never asks.")
NOTE = ("The PayPal donate page in a browser window (its own private profile). Nothing is paid unless you choose to on that page. "
        "Press Esc twice (or hold Guide + B on a controller) to return to Code.")
