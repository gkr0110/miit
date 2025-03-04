# Try multi stage build
FROM mwess89/greedyfhist:0.0.3-rc1 as base


# Clone repositories and install Python packages in a separate stage
FROM base as builder
RUN git clone --depth 1 --branch v0.0.3-rc1 https://github.com/mwess/greedyfhist /greedyfhist
RUN git clone --depth 1 --branch v0.0.3-rc1 https://github.com/mwess/miit /miit
RUN pip install /greedyfhist /miit jupyterlab

# Create the final image
FROM base
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

EXPOSE 8888
CMD ["jupyter", "lab", "--port=8888", "--no-browser", "--ip=0.0.0.0", "--allow-root"]
