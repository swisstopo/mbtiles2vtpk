FROM python:3.12-slim

WORKDIR /app

# Copy repo (submodule included)
COPY . .

# Install package (no extra dependencies beyond the submodule)
RUN pip install --no-cache-dir -e .

ENTRYPOINT ["mbtiles2vtpk"]
