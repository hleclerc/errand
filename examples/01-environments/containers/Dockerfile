FROM python:3-slim

# errand rebuilds the image when this file changes; the fingerprint it keeps
# covers the recipe and the pip list of the layer that names it.
RUN pip install --no-cache-dir numpy
