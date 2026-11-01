"""The owner's navigation test: JEV is shown a picture of the window and nothing else, and has to find its own way.

Same sandboxed browser, same loop and same stops as the standard decider (loop.py): payment and sign-in stops, the denied-sites list, address checks, a clean profile, step and time
limits, budget, Stop and hand-over. The code that reads the page for those rules still reads it. Only JEV is told less. What changes (and nothing else):
  * JEV gets no control list and no page text: the prompt carries the goal, the address (host and path), what was already done, and the window picture (ladder.choose_picture);
  * the prompt says only that the picture is all it is given (no "a popup is probably in the way");
  * every click or typed text is a spot in the picture; the loop names what is there (probe) and runs its rules before anything happens, as for any picture step;
  * nobody else decides a step: no take-over by the assistant, and when JEV misses twice, repeats itself or asks for a choice, the task STOPS with the reason, so the result shows how far
    JEV got alone. (When JEV says `done`, the assistant still confirms it and writes the answer, as in the standard path; it does not steer.)
Switched on only for the owner's own account, with a time limit, from the Safety console (`jev_sees_controls` OFF), and read when a task starts.
"""
from .ladder import JevChooser


class PictureOnlyChooser(JevChooser):
    picture_only = True
    neutral_picture = True        # the picture is all it is given, so it is not told a popup is probably in the way
