"""What this project does, as opposed to where it runs ( that is `errand-envs.py` ).

Ordinary Python, loaded once, with every other `errand-*.py`.
"""
import errand

errand.configure(
    src = [ "src" ],           # prepended to every child's PYTHONPATH
)
