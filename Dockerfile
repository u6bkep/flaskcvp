FROM python:3.11

ARG SLICE_NAME=MumbleServerv1.5.735.ice
ARG MURMUR_CONNECT_URL="http://www.mumble.info/"

RUN pip install --no-cache-dir flask zeroc-ice requests pillow

RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

COPY mumble/ mumble/
COPY templates/ templates/
COPY slices/${SLICE_NAME} setup_flaskcvp.py flaskcvp.py ./

ENV MUMBLE_CONNSTRING=Meta\ -e\ 1.0:tcp\ -h\ mumble-server\ -p\ 6502
ENV MUMBLE_ICESECRET=password
ENV MUMBLE_SLICE=${SLICE_NAME}
ENV FLASKCVP_HOST=::
ENV FLASKCVP_PORT=5000
ENV MURMUR_CONNECT_URL=${MURMUR_CONNECT_URL}

ENTRYPOINT [ "python", "./flaskcvp.py" ]
