FROM python:3-alpine

COPY app_activity_report.py /
COPY templates/ /templates/

RUN pip install flask~=2.0.0

ENTRYPOINT ["/app_activity_report.py"]
