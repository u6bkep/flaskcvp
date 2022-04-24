FROM python:2.7

RUN pip install --no-cache-dir flask zeroc-ice requests pillow

RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

COPY mumble/ mumble/
COPY murmur1.4.ice setup_flaskcvp.py PKG-INFO flaskcvp.py ./

ENV MURMUR_CONNECT_URL="http://www.mumble.info/"

ENTRYPOINT [ "python", "./flaskcvp.py" ]

CMD ["-c", "Meta -e 1.0:tcp -h murmur -p 6502", "-H", "::", "-s", "murmur1.4.ice"]
