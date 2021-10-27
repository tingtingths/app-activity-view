#!/usr/bin/env python3
import argparse
import itertools
import json
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, render_template, request

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
rendered_cache = {}


@app.route('/test')
def test():
    with open('sample.ndjson', 'r') as f:
        records = parse_ndjson(f.read())
        parsed = parse_activities(records)
    render_params = {
        "accesses": parsed['accesses'],
        "network_activities": parsed['network_activities']
    }
    return render_template('report.html', **render_params)


@app.route("/<path:rendered_id>", methods=['GET'])
def render_report_from_b64(rendered_id):
    try:
        html = rendered_cache[rendered_id]['content']
        del rendered_cache[rendered_id]
    except:
        return "Not Found", 404
    return html


@app.route("/", methods=['POST'])
def render_report():
    if "file" not in request.files or request.files["file"] is None:
        return 'file not present', 400
    records = parse_ndjson(request.files["file"].stream.read().decode("utf-8"))
    parsed = parse_activities(records)
    render_params = {
        "accesses": parsed['accesses'],
        "network_activities": parsed['network_activities']
    }
    req_args = request.args
    if 'url' in req_args and req_args['url'].lower() == 'true':
        uuid_hex = uuid.uuid4().hex
        rendered_cache[uuid_hex] = {
            'generated': time.time(),
            'content': render_template('report.html', **render_params)
        }
        return {
            "id": uuid_hex
        }
    return render_template('report.html', **render_params)


@app.template_filter('fmt_access')
def fmt_access(access):
    start_time = datetime.fromisoformat(access['start']['timeStamp'])
    end_time = datetime.fromisoformat(access['end']['timeStamp'])
    duration_second = int(end_time.timestamp() -
                          start_time.timestamp())
    duration_second = 1 if duration_second == 0 else duration_second
    return {
        'category': access['category'],
        'start_datetime': start_time.strftime('%Y-%m-%d %H:%M:%S'),
        'start_date': start_time.strftime('%Y-%m-%d'),
        'duration': duration_second
    }


@app.template_filter('fmt_timestamp')
def fmt_timestamp(time_str):
    return datetime.fromisoformat(time_str).strftime('%Y-%m-%d %H:%M:%S')


@app.template_filter('fmt_timestamp_to_date')
def fmt_timestamp_to_date(time_str):
    return datetime.fromisoformat(time_str).strftime('%Y-%m-%d')


@app.template_filter('access_summary')
def access_summary(access_pairs):
    sorted_pairs = sorted(access_pairs, key=lambda x: x['category'])
    return sorted({
                      cat: len(list(grouped_pairs))
                      for cat, grouped_pairs in itertools.groupby(sorted_pairs, key=lambda x: x['category'])
                  }.items(), key=lambda item: item[1], reverse=True)


@app.template_filter('filter_access_by_date')
def filter_access_by_date(access_pairs, access):
    target_date = fmt_timestamp_to_date(access['start']['timeStamp'])
    return list(filter(lambda x: target_date == fmt_timestamp_to_date(x['start']['timeStamp']), access_pairs))


def print_network_activities(_network_activities):
    for bundle, activities in _network_activities.items():
        print(f'{bundle}')
        for activity in activities:
            cntx = f'{activity["context"]} -> ' if activity["context"] != "" else ""
            print(f'\t({activity["hits"]})\t{cntx}{activity["domain"]}')


def print_access(_access):
    def get_or_empty(_dict, _key):
        if _key in _dict:
            return _dict[_key]
        return ''

    for bundle, access_pairs in _access.items():
        print(bundle)
        for pair in access_pairs:
            start_time = datetime.fromisoformat(pair['start']['timeStamp'])
            end_time = datetime.fromisoformat(pair['end']['timeStamp'])
            duration_second = int(end_time.timestamp() -
                                  start_time.timestamp())
            duration_second = 1 if duration_second == 0 else duration_second
            print(
                f'\t[{pair["category"]}]\t{start_time} for {duration_second} seconds')


def parse_ndjson(s):
    records = []
    for line in s.split('\n'):
        if line:
            records.append(json.loads(line))
    return records


def parse_activities(records):
    parsed = {}
    # parse network activities
    # group by 'bundleID'
    lst = filter(lambda x: x['type'] == 'networkActivity', records)
    parsed['network_activities'] = {
        bundle: sorted(network_acts, reverse=True, key=lambda act: act['hits'])
        for bundle, network_acts in itertools.groupby(lst, lambda el: el['bundleID'])
    }

    def pair_to_obj(_pair):
        lst = list(_pair)
        return {
            'id': lst[0]['identifier'],
            'category': lst[0]['category'],
            'start': list(filter(lambda x: x['kind'] == 'intervalBegin', lst))[0],
            'end': list(filter(lambda x: x['kind'] == 'intervalEnd', lst))[0]
        }

    # parse access
    lst = sorted(list(filter(
        lambda x: x['type'] == 'access', records)), key=lambda x: x['accessor']['identifier'])
    parsed['accesses'] = {
        bundle: sorted([
            # group by activities' identifier
            pair_to_obj(pair)
            for _, pair in itertools.groupby(sorted(acts, key=lambda x: x['identifier']), lambda x: x['identifier'])
        ], reverse=True, key=lambda x: datetime.fromisoformat(x['start']['timeStamp']).timestamp())
        for bundle, acts in itertools.groupby(lst, lambda x: x['accessor']['identifier'])
    }

    return parsed


if __name__ == '__main__':
    # file = sys.argv[1]
    # records = []
    # with open(file, 'r') as f:
    #     # from ndjson to json
    #     raw = f'[{f.read()}]'
    #     raw = raw.replace('\n', '')
    #     raw = raw.replace('}{', '},{')
    #     records = json.loads(raw)
    #     # print(records)
    # parsed = parse_activities(records)
    # print_access(parsed['access'])
    # print_network_activities(parsed['network_activities'])
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', default=80, type=int, help='port')
    parser.add_argument('-b', '--bind', default='127.0.0.1', type=str, help='binding address')
    args = parser.parse_args()


    def check_expire():
        while True:
            now = time.time()
            expired = [k for k, v in rendered_cache.items() if (now - v['generated']) > 60]
            try:
                if len(expired) > 0:
                    for k in expired:
                        del rendered_cache[k]
                    print(f'expired: {expired}')
            except:
                pass
            time.sleep(1)


    threading.Thread(daemon=True, target=check_expire).start()

    app.run(port=args.port, host=args.bind)
