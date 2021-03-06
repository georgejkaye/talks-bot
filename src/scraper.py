import re
from more_itertools import split_at
import requests
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from textwrap import fill
from html import unescape
from debug import debug

datetime_regex = r'([A-Za-z]+) ([0-3][0-9]) ([A-Za-z]+) ([0-9][0-9][0-9][0-9]), ([0-2][0-9]:[0-5][0-9])-([0-2][0-9]:[0-5][0-9])'
speaker_url_regex = r'\"\/user\/show\/([0-9]*)\"'

line_width = 80


def wrap_string(string, width):
    """
    Wrap a string at a given line width.

    Nabbed from https://stackoverflow.com/a/26538082
    """
    paragraphs = string.split("\n")
    output = fill(paragraphs[0], width)
    for para in paragraphs[1:]:
        output = output + "\n" + fill(para, width)
    return output


class Talk:
    def __init__(self, seminar, title, speaker, institution, link, date, start, end, abstract):
        self.title = title
        self.series = seminar.name
        self.speaker = speaker
        self.institution = institution
        self.link = link
        self.date = date
        self.room = seminar.room
        self.zoom = seminar.zoom
        self.announce_datetime = date - \
            timedelta(days=seminar.announce.days_before)

        # account for weekends
        if self.announce_datetime.weekday() == 5 or self.announce_datetime.weekday() == 6:
            self.announce_datetime = self.announce_datetime - timedelta(days=2)

        self.announce_datetime = self.announce_datetime.replace(
            hour=seminar.announce.time)
        self.reminder_datetime = date.replace(hour=seminar.reminder.time)

        self.start = start
        self.end = end
        self.abstract = abstract
        self.wrapped_abstract = wrap_string(abstract, line_width)
        self.has_missing_components = self.title == "Title to be confirmed" or self.abstract == "Abstract not available"

    def get_institution(self):
        if self.institution is None:
            return ""
        return f"({self.institution})S"

    def get_long_datetime(self):
        return datetime.strftime(self.date, "%A %d %B %Y") + ", " + self.start + "-" + self.end

    def get_mid_datetime(self):
        return datetime.strftime(self.date, "%A %d %B")

    def get_short_datetime(self):
        return datetime.strftime(self.date, "%a %d %b") + " @ " + self.start

    def get_announce_time(self):
        return datetime.strftime(self.announce_date, "%A %d %B")


talks_url_base = "http://talks.bham.ac.uk"


def get_talks_page(id):
    return f"{talks_url_base}/show/index/{id}"


def get_speaker_page(id):
    return f"{talks_url_base}/user/show/{id}"


def get_talks_xml_url(id, range):
    seconds = range * 86400
    return f"{talks_url_base}/show/xml/{id}?seconds_before_today=0&seconds_after_today={seconds}"


def make_request(config, link):
    debug(config, f"Making request to {link}")
    page = requests.get(link)
    if page.status_code != 200:
        debug(config,
              f"Error {page.status_code}: could not get page {link}")
        exit(1)
    return page.content


def in_next_days(date, range):
    today = datetime.datetime.today()
    range = datetime.timedelta(days=range)
    return date <= today + range


def get_next_talk(config, seminar):
    # We only want to get seminars happening in the next week
    days_to_search = 6
    seminar_page = get_talks_xml_url(seminar.talks_id, days_to_search)

    upcoming_talks = make_request(config, seminar_page)

    tree = ET.ElementTree(ET.fromstring(upcoming_talks))
    root = tree.getroot()

    series_name = root.find("name").text

    talks = root.findall("talk")

    for talk in talks:
        # Talks can be crossposted between lists so this means that talks
        # not in the 'core' series can be overridden by closer 'bonus' talks
        # So we need to check it's in the right series
        if talk is not None and talk.find("series").text == series_name:

            talk_title = unescape(talk.find("title").text)
            talk_speaker_and_institution = talk.find("speaker").text

            # Usually the speaker field has an institution in brackets alongside
            # the actual speaker name. We need to strip this off, so we search
            # for the bracket. However, the brackets might not be there in the
            # first place as not all speakers have institutions, and not all
            # list admins are big brain enough to put them in. Moreover, sometimes
            # there might be additional brackets in the field, if the speaker
            # has a nickname or something. I'm not sure if this handles all the
            # cases but I guess we'll see.
            split_at_bracket = talk_speaker_and_institution.split("(")

            if len(split_at_bracket) == 1:
                talk_speaker = split_at_bracket[0]
                talk_institution = None
            else:
                talk_institution = split_at_bracket[-1][:-1]
                talk_speaker = "(".join(split_at_bracket[:-1])[:-1]

            talk_link = talk.find("url").text
            talk_start_date_and_time = talk.find("start_time").text
            date_string = talk_start_date_and_time[0:-15]
            talk_date = datetime.strptime(
                date_string, "%a, %d %b %Y")
            talk_start = talk_start_date_and_time[-14:-9]
            talk_end = talk.find("end_time").text[-14:-9]
            abstract_string = talk.find("abstract").text

            # In a perfect world we would have separate fields for all the zoom stuff.
            # Unfortunately talks was made in the noughties and there were no major global
            # pandemics at that point. As a workaround I try to have an *Abstract* tag to
            # distinguish where the abstract proper starts. If this is found, then all the
            # text after this will be put in. Otherwise, the whole textbox will be dumped in.
            split_at_abstract_tag = abstract_string.split("*Abstract*\n\n")

            if len(split_at_abstract_tag) > 1:
                abstract_string = split_at_abstract_tag[-1]
            else:
                abstract_string = split_at_abstract_tag[0]

            return Talk(seminar, talk_title, talk_speaker, talk_institution, talk_link, talk_date, talk_start, talk_end, abstract_string)

    return None
