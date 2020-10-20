#%%

# pdfminer:  pip install pdfminer.six
import collections, glob, io, json, os, pdfminer, pdfminer.high_level, pprint, re
from more_itertools import chunked

# Coordinate system:
#
# Y increases up;  X increases right
#
#           y2: top
# x1: left              x2: right
#           y1: bottom
#
class PdfSpan:
    def __init__(self, lt=None, parser=None, x1=None, y1=None, x2=None, y2=None, text=''):
        if lt and parser and x1 == None and y1 == None and x2 == None and y2 == None:
            self.parser = parser
            (self.x1, self.y1, self.x2, self.y2) = lt.bbox
            self.text = lt.get_text().strip()
        elif lt == None and parser == None and x1 != None and y1 != None and x2 != None and y2 != None:
            self.parser = None
            assert(x1 <= x2)
            assert(y1 <= y2)
            self.x1 = x1
            self.y1 = y1
            self.x2 = x2
            self.y2 = y2
            self.text = text
        else:
            assert(False)

    def translate(self, dx, dy):
        self.x1 += dx
        self.x2 += dx
        self.y1 += dy
        self.y2 += dy

    # centroid
    @property
    def x(self):
        return (self.x1 + self.x2) / 2

    # centroid
    @property
    def y(self):
        return (self.y1 + self.y2) / 2

    def matches(self, literal=None, regex=None):
        if literal != None:
            return self.text == literal
        elif regex != None:
            return not not re.match(regex, self.text)
        assert False

    def overlaps_vertically(self, rhs):
        if self.y2 < rhs.y1 or rhs.y2 < self.y1:
            return False
        return True

    def overlaps_horizontally(self, rhs):
        if self.x2 < rhs.x1 or rhs.x2 < self.x1:
            return False
        return True

    def overlaps(self, rhs):
        return self.overlaps_horizontally(rhs) and self.overlaps_vertically(rhs)

    def centroid_within_vertical_span(self, rhs):
        return rhs.y1 <= self.y and self.y <= rhs.y2


    def centroid_within_horizontal_span(self, rhs):
        return rhs.x1 <= self.x and self.x <= rhs.x2

    def centroid_within(self, rhs):
        return self.centroid_within_horizontal_span(rhs) and self.centroid_within_vertical_span(rhs)

    def union(self, rhs):
        return PdfSpan(text=self.text + ' ' + rhs.text,
                       x1=min(self.x1, rhs.x1),
                       y1=min(self.y1, rhs.y1),
                       x2=max(self.x2, rhs.x2),
                       y2=max(self.y2, rhs.y2))

    @staticmethod
    def merge(spans):
        ret = spans[0]
        for span in spans[1:]:
            ret = ret.union(span)
        return ret

    def __repr__(self):
        return f"<'{self.text}' x:{self.x:.2f}({self.x1:.2f}-{self.x2:.2f}) y:{self.y:.2f}({self.y1:.2f}-{self.y2:.2f})>"

    def copy_to_parser(self, parser):
        ret = copy.copy(self)
        ret.parser = parser
        return ret

class PdfParser:
    def __init__(self, pdf_content=None, page_offset = 100, spans=None):
        assert ((pdf_content is not None and spans is None) or
                (pdf_content is None and spans is not None))
        if spans is not None:
            self.spans = spans
        else:
            self.spans = []
            parser = pdfminer.pdfparser.PDFParser(io.BytesIO(pdf_content))
            document = pdfminer.pdfdocument.PDFDocument(parser)
            if not document.is_extractable:
                raise Exception('PDF text extraction not allowed')
            rsrcmgr = pdfminer.pdfinterp.PDFResourceManager()
            device = pdfminer.converter.PDFPageAggregator(rsrcmgr, laparams=pdfminer.layout.LAParams())
            interpreter = pdfminer.pdfinterp.PDFPageInterpreter(rsrcmgr, device)

            def find_lines(obj):
                ret = []
                if isinstance(obj, pdfminer.layout.LTTextLineHorizontal):
                    ret.append(obj)
                elif hasattr(obj, '_objs'):
                    for o in obj._objs:
                        ret += find_lines(o)
                return ret

            pages = []
            for page in reversed(list(pdfminer.pdfpage.PDFPage.create_pages(document))):
                interpreter.process_page(page)
                pages.append(find_lines(device.get_result()))

            # Concatenate pages, with page_offset spacing in-between
            y_offset = 0
            max_y = 0
            for page in pages:
                for line in page:
                    span = PdfSpan(lt=line, parser=parser)
                    span.translate(0, y_offset)
                    self.spans.append(span)
                    max_y = max(max_y, span.y2)
                y_offset = max_y + page_offset

        self._init_sort_spans_lexically()

    ### Sort spans lexically into rows
    def _init_sort_spans_lexically(self):
        # Sort top to bottom
        spans = sorted(self.spans, key=lambda s:s.y, reverse=True)

        rows = []
        while spans:
            top = spans[0]
            row = []
            while spans and spans[0].y >= top.y1:
                row.append(spans.pop(0))
            rows.append(sorted(row, key=lambda s:s.x))
        self.rows = rows
        self.spans = sum(rows, [])
        

    def find_all(self, literal=None, regex=None):
        return [span for span in self.spans if span.matches(literal=literal, regex=regex)]

    def find(self, literal=None, regex=None):
        spans = self.find_all(literal=literal, regex=regex)
        if len(spans) == 1:
            return spans[0]
        elif len(spans) == 0:
            raise Exception(f'No match')
        else:
            raise Exception(f'Too many matches')

    def find_sequence(self, literals):
        candidates = self.find_all(literals[0])
        for span in candidates:
            ret = [span]
            for literal in literals[1:]:
                span = self.next(span)
                if span and span.matches(literal):
                    ret.append(span)
                else:
                    break
            if len(ret) == len(literals):
                return ret
        raise Exception(f'Cant find sequence {literals}')

    def find_sequence_as_span(self, literals):
        seq = self.find_sequence(literals)
        return PdfSpan.merge(seq)

    def next(self, span):
        assert(span)
        best = None
        for candidate in self.spans:
            if span.overlaps_vertically(candidate) > 0 and span.x < candidate.x:
                if not best or candidate.x1 < best.x1:
                    best = candidate
        return best

    def prev(self, span):
        assert(span)
        best = None
        for candidate in self.spans:
            if span.overlaps_vertically(candidate) > 0 and candidate.x2 < span.x1:
                if not best or candidate.x2 > best.x2:
                    best = candidate
        return best

    def first_row(self):
        if not self.spans:
            return None
        return self.beginning_of_row(max(self.spans, key=lambda span:span.y))

    def next_row(self, span):
        assert(span)

        # Find a span somewhere on the next row
        best = None
        for candidate in self.spans:
            if span.y1 > candidate.y2:
                if not best or candidate.y1 > best.y1:
                    best = candidate

        return best and self.beginning_of_row(best)

    def beginning_of_row(self, span):
        while True:
            test = self.prev(span)
            if test:
                span = test
            else:
                break
        return span

    def spans_from_row(self, row):
        row = self.beginning_of_row(row)
        ret = [row]
        while True:
            test = self.next(row)
            if not test:
                return ret
            ret.append(test)
            row = test

    def text_from_row(self, row):
        return ' '.join([span.text for span in self.spans_from_row(row)])

    def extract_after(self, span, until=None):
        ret = []
        while True:
            next = self.next(span)
            if not next or next == until:
                return ' '.join(ret)
            ret.append(next.text)
            span = next

    def extract_table(self, header, until_gap, master_column=None, end_regex=None):
        row = header[0]
        parsed_rows = []
        while True:
            next = self.next_row(row)
            if not next or row.y2 - next.y1 >= until_gap:
                break
            row = next
            if not end_regex is None and re.search(end_regex,row.text):
                #print(f"Found end_regex {end_regex} at {row}")
                break
            parsed_row = collections.defaultdict(lambda:[])
            for span in self.spans_from_row(row):
                col_heads = [col_head for col_head in header if col_head.overlaps_horizontally(span)]
                if len(col_heads) == 0:
                    raise Exception(f'Content {span} does not match any columns')
                elif len(col_heads) > 1:
                    raise Exception(f'Content {span} matches multiple columns {col_heads}')
                else:
                    parsed_row[col_heads[0].text].append(span.text)
            parsed_rows.append(parsed_row)

        # If master_column, merge any rows missing master_column with row above
        merged_rows = []
        to_merge = None
        for row in reversed(parsed_rows):
            if to_merge:
                for (k,v) in to_merge.items():
                    row[k] += v
                to_merge = None
            if master_column and not master_column.text in row:
                to_merge = row
            else:
                merged_rows.append(row)
        if to_merge:
            merged_rows.append(row)

        # reverse back to forward order, and join all the lines for each value
        return [{k:' '.join(v) for (k,v) in row.items()} for row in reversed(merged_rows)]

    def compute_document_span_box(self):
        ret = None
        for span in self.spans[1:]:
            if ret:
                ret = ret.union(span)
            else:
                ret = span
        return ret

    def box(self,
            bottom_including=None, bottom_excluding=None,
            top_including=None, top_excluding=None,
            left_including=None, left_excluding=None,
            right_including=None, right_excluding=None):

        ret = self.compute_document_span_box()

        if bottom_including:
            ret.y1 = bottom_including.y1
            assert not bottom_excluding
        elif bottom_excluding:
            ret.y1 = bottom_excluding.y2

        if top_including:
            ret.y2 = top_including.y2
            assert not top_excluding
        elif top_excluding:
            ret.y2 = top_excluding.y1

        if left_including:
            ret.x1 = left_including.x1
            assert not left_excluding
        elif left_excluding:
            ret.x1 = left_excluding.x2

        if right_including:
            ret.x2 = right_including.x2
            assert not right_excluding
        elif right_excluding:
            ret.x2 = right_excluding.x1

        return ret

    # Return cropped subset
    def extract_box(self, box):
        spans = [span for span in self.spans if span.centroid_within(box)]
        ret = PdfParser(spans=spans)
        return ret

    # Join spans with space (even between rows)
    def extract_text(self, box=None):
        if box:
            parser = self.extract_box(box)
        else:
            parser = self
        return ' '.join([span.text for span in parser.spans])

    # Join spans with space, or \n between rows
    def extract_text_lines(self):
        lines = [' '.join([span.text for span in row]) for row in self.rows]
        return '\n'.join(lines)

def parse_pa_mdj_docket(parser, verbose=False):
    ret = collections.defaultdict(lambda:{})

    # Case Info
    # Call with subparser that contains only the ROI
    def parse_case(parser):
        case = {}
        case['Judge Assigned'] = parser.extract_text(parser.box(
            top_including=parser.find('Judge Assigned:'),
            left_excluding=parser.find('Judge Assigned:'), right_excluding=parser.find('File Date:'),
            bottom_excluding=parser.find('Claim Amount:')))

        case['File Date'] = parser.extract_text(parser.box(
            top_including=parser.find('File Date:'),
            left_excluding=parser.find('File Date:'),
            bottom_excluding=parser.find('Case Status:')))

        case['Claim Amount'] = parser.extract_text(parser.box(
            top_including=parser.find('Claim Amount:'),
            left_excluding=parser.find('Claim Amount:'), right_excluding=parser.find('Case Status:'),
            bottom_excluding=parser.find('Judgment Amount:')))

        case['Case Status'] = parser.extract_text(parser.box(
            top_including=parser.find('Case Status:'),
            left_excluding=parser.find('Case Status:'),
            bottom_excluding=parser.find('County:')))

        case['Judgment Amount'] = parser.extract_text(parser.box(
            top_including=parser.find('Judgment Amount:'),
            left_excluding=parser.find('Judgment Amount:'), right_excluding=parser.find('County:')))

        case['County'] = parser.extract_text(parser.box(
            top_including=parser.find('County:'),
            left_excluding=parser.find('County:')))

        return case

    # Sometimes there's more than one block within CASE INFORMATION.C
    # Construct a list of "landmarks", between which we'll find each block
    
    # For mature cases, the next section will be CALENDAR EVENTS.  
    # However, for newly minted cases that don't yet have that section we need to fall back on 'CASE PARTICIPANTS'
    judge_end_landmarks = parser.find_all('CALENDAR EVENTS')+parser.find_all('CASE PARTICIPANTS')
    assert len(judge_end_landmarks)>0, 'Cannot find end landmark for Judge Assigned:'
    case_info_landmarks = parser.find_all('Judge Assigned:') + judge_end_landmarks[0:1]
    case_infos = []
    for (top, bottom) in zip(case_info_landmarks[:-1], case_info_landmarks[1:]):
        case_infos.append(parse_case(parser.extract_box(parser.box(top_including=top, bottom_excluding=bottom))))

    if len(case_infos) == 1:
        # ret['Case Info'] is a dict for the standard case of one case info block
        ret['Case Info'] = case_infos[0]
    elif len(case_infos) > 1:
        # ret['Case Info'] is array of dicts when more than one case info block
        ret['Case Info'] = case_infos
    else:
        raise Exception('No "Judge Assigned:"')

    # Participants
    header = parser.find_sequence(['Participant Type', 'Participant Name', 'Address'])
    ret['Participants'] = parser.extract_table(header, until_gap=23, end_regex="DISPOSITION", master_column=header[0])

    # Diposition Summary
    header = parser.find_sequence(['Docket Number', 'Plaintiff', 'Defendant', 'Disposition', 'Disposition Date'])
    ret['Disposition Summary'] = parser.extract_table(header, until_gap=23, master_column=header[-1],end_regex='CIVIL DISPOSITION / JUDGMENT DETAILS')

    # Civil Disposition Details
    ret['Civil Disposition Details']['Grant possession.'] = parser.extract_after(parser.find('Grant possession.'))
    ret['Civil Disposition Details']['Grant possession if money judgment is not satisfied by the time of eviction.'] = \
        parser.extract_after(parser.find('Grant possession if money judgment is not satisfied by the time of eviction.'))

    # Civil Disposition / Judgment Details (optional)
    if parser.find_all('CIVIL DISPOSITION / JUDGMENT DETAILS'):
        def parse_civil_disposition(parser):
            disp_rent_text = parser.text_from_row(parser.find(regex=r'^Disposition Date:'))
            match = re.match(r'Disposition Date:\s+(\S*)\s+Monthly Rent:\s*(\S*)\s*$', disp_rent_text)
            if not match:
                raise Exception(f'Could not parse civil disposition / judgement details: {disp_rent_text}')
            civil_disposition = {}
            civil_disposition['Disposition Date'] = match[1]
            civil_disposition['Monthly Rent'] = match[2]

            header = parser.find_sequence(['Defendant(s)', 'Plaintiff(s)', 'Disposition', 'Liability', 'Liability', 'Judgment'])
            # Header is two lines;  edit the header span texts to add the first line, which wasn't matched
            # This mutates the parse, so just be aware
            header[3].text = 'Joint/Several Liability'
            header[4].text = 'Individual Liability'
            header[5].text = 'Net Judgment'
            civil_disposition['Judgment'] = parser.extract_table(
                header, until_gap=23, master_column=header[-1], end_regex="Judgment Components")

            header = parser.find_sequence(['Type', 'Amount', 'Deposit Amount', 'Adjusted Amount'])
            civil_disposition['Judgment Components'] = parser.extract_table(header, until_gap=23, master_column=header[-1])
            return civil_disposition

        disposition_landmarks = parser.find_all(regex=r'^Disposition Date:')
        civil_dispositions = []
        for (top, bottom) in zip(disposition_landmarks, [*disposition_landmarks[1:], None]):
            box = parser.box(top_including=top, bottom_excluding=bottom)
            civil_dispositions.append(parse_civil_disposition(parser.extract_box(box)))

        if len(civil_dispositions) == 1:
            # ret['Civil Disposition'] is a dict for the standard case of one disposition
            ret['Civil Disposition'] = civil_dispositions[0]
        elif len(civil_dispositions) > 1:
            # ret['Civil Disposition'] is array of dicts when more than one disposition
            ret['Civil Disposition'] = civil_dispositions
        else:
            raise Exception('No "Disposition Date:"')

    # Attorney Info
    if parser.find_all('ATTORNEY INFORMATION'):
        subparser = parser.extract_box(parser.box(top_excluding=parser.find('ATTORNEY INFORMATION'), bottom_excluding=parser.find('DOCKET ENTRY INFORMATION')))
        # Try to split into two columns, and extract text
        withdrawal = subparser.find_all(regex='^Withdrawal of Entry of Appearance Filed Dt:')
        withdrawal = sorted(withdrawal, key=lambda s: s.x)
        assert(len(withdrawal) == 1 or len(withdrawal) == 2)
        text = subparser.extract_box(parser.box(right_excluding=withdrawal[-1])).extract_text_lines()
        if text:
            text += '\n'
        text += subparser.extract_box(parser.box(left_including=withdrawal[-1])).extract_text_lines()
        pattern = r'''([^\n]+?)
(Name):(.*?)
(Representing):(.*?)
(Counsel Status):(.*?)
(Supreme Court No.):(.*?)
(Phone No.):(.*?)
(Address):(.*?)
(Entry of Appearance Filed Dt):(.*?)
(Withdrawal of Entry of Appearance Filed Dt):(.*?)'''

        infos = []
        for match in re.finditer(pattern, text, re.DOTALL):
            info = {}
            groups = match.groups()
            info['Header'] = groups[0]
            for k,v in chunked(groups[1:], 2):
                v = v.strip()
                # Preserve newlines only for Address
                if k != 'Address':
                    # Replace any string of whitespace with single space
                    v = re.sub('\s+', ' ', v)
                info[k] = v
            infos.append(info)
        ret['Attorney Info'] = infos

    # Docket Entry Info
    header = parser.find_sequence(['Filed Date', 'Entry', 'Filer', 'Applies To'])
    ret['Docket Entry Info'] = parser.extract_table(header, until_gap=60, end_regex='MDJS 1200|Printed:', master_column=header[0])

    # Calendar Events
    if parser.find_all('CALENDAR EVENTS'):
        header = parser.find_sequence(['Event Type', 'Start Date', 'Start Time', 'Room', 'Judge Name', 'Status'])
        # Header is two lines;  edit the header span texts to add the first line, which wasn't matched
        # This mutates the parse, so just be aware
        header[0].text = 'Case Calendar Event Type'
        header[1].text = 'Schedule Start Date'
        header[5].text = 'Schedule Status'
        ret['Calendar Events'] = parser.extract_table(header, until_gap=60, end_regex="CASE PARTICIPANTS", master_column=header[-1])

    return dict(ret)

#%%
if False:
    for src in glob.glob('tests/*.pdf'):
        print(f'\n\n********************\n{src}')
        docket = parse_pa_mdj_docket(PdfParser(pdf_content = open(src, 'rb').read()))
        print(json.dumps(docket, indent=2))
        if os.path.basename(src) == 'MDJReport-10.pdf':
            assert(docket['Calendar Events'] == [
                {
                    'Case Calendar Event Type': 'Recovery of Real Property Hearing',
                    'Schedule Start Date': '03/30/2020',
                    'Start Time': '1:30 pm',
                    'Judge Name': 'Magisterial District Judge Thomas Carney',
                    'Schedule Status': 'Scheduled'
                }
            ])

# %%


