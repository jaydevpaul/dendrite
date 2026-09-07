"""Server-sent events: one named event per frame, JSON in every data line"""

import json
from typing import Any

def frame(event:str, data:dict[str,Any]):
    """One SSE frame: a named event and a single JSON data line.

    The data is JSON always, even when it is one string. Frames are separated
    by a blank line, so a bare newline inside a `data:` line ends the frame
    early and everything after it is read as a new frame - and model output is
    full of newlines. That failure does not look like a transport bug: it looks
    like the model producing broken markdown.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"





