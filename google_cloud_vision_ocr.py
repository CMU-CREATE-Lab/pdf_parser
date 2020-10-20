#%%

# Using example from here:
# https://cloud.google.com/vision/docs/ocr
# (click on Python)

#  TODO
# download auth keys into keys/auth.json
# try api with scanned, and with digital pdf

# Point to our credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = f"{os.path.dirname(os.path.realpath(__file__))}/keys/rsargent-paid-cloud-vision-auth.json"

import binascii, datetime, os, subprocess, json, glob

# On Nadiya's computer, run command prompt then
# cd ~\anaconda3\Scripts
# .\activate


# Install with pip install google-cloud-vision
from google.cloud import vision
# Install with pip install google-cloud-storage
from google.cloud import storage

from pdfparser import PdfSpan, PdfParser
#%%

# For Randy's laptop
#gsutil_path = '/Users/rsargent/google-cloud-sdk/bin/gsutil'

# For Nadiya's PC
gsutil_path = r'C:\Users\Nadz\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gsutil.cmd'


print('gsutil version:')
try:
    print(subprocess.check_output([gsutil_path, '--version']))
except Exception as e:
    print('Could not find gsutil executable.  Please install or change gsutil_path to point to it')
    print(e)

print('Be sure to run gcloud auth login the first time')


# We're using rsargent-paid google project
bucket_name = 'pdfparser-cloud-vision-upload'
#results.pages[0].blocks[2].paragraphs[0].words[0].symbols[0]

def assemble_word(word):
    ret = ''
    for symbol in word.symbols:
        ret = ret + symbol.text
    return ret

def pdfspan_from_word(word):
    text = assemble_word(word)
    vertices = word.bounding_box.normalized_vertices
    return PdfSpan(
        x1=(min(vertices[0].x, vertices[1].x, vertices[2].x, vertices[3].x)*100)-.05,
        y2=100-min(vertices[0].y, vertices[1].y, vertices[2].y, vertices[3].y)*100-.05,
        x2=(max(vertices[0].x, vertices[1].x, vertices[2].x, vertices[3].x)*100)+.05,
        y1=100-max(vertices[0].y, vertices[1].y, vertices[2].y, vertices[3].y)*100+.05,
        text=text)


def async_detect_document(gcs_source_uri, gcs_destination_uri):
    """OCR with PDF/TIFF as source files on GCS"""
    import re
    from google.cloud import vision
    from google.cloud import storage
    from google.protobuf import json_format
    # Supported mime_types are: 'application/pdf' and 'image/tiff'
    mime_type = 'application/pdf'

    # How many pages should be grouped into each json output file.
    batch_size = 2

    client = vision.ImageAnnotatorClient()

    feature = vision.types.Feature(
        type=vision.enums.Feature.Type.DOCUMENT_TEXT_DETECTION)

    gcs_source = vision.types.GcsSource(uri=gcs_source_uri)
    input_config = vision.types.InputConfig(
        gcs_source=gcs_source, mime_type=mime_type)

    gcs_destination = vision.types.GcsDestination(uri=gcs_destination_uri)
    output_config = vision.types.OutputConfig(
        gcs_destination=gcs_destination, batch_size=batch_size)

    async_request = vision.types.AsyncAnnotateFileRequest(
        features=[feature], input_config=input_config,
        output_config=output_config)

    operation = client.async_batch_annotate_files(
        requests=[async_request])

    print('Waiting for the operation to finish.')
    operation.result(timeout=420)

    # Once the request has completed and the output has been
    # written to GCS, we can list all the output files.
    storage_client = storage.Client()

    match = re.match(r'gs://([^/]+)/(.+)', gcs_destination_uri)
    bucket_name = match.group(1)
    prefix = match.group(2)

    bucket = storage_client.get_bucket(bucket_name)

    # List objects with the given prefix.
    blob_list = list(bucket.list_blobs(prefix=prefix))
    print('Output files:')
    for blob in blob_list:
        print(blob.name)

    # Process the first output file from GCS.
    # Since we specified batch_size=2, the first response contains
    # the first two pages of the input file.
    output = blob_list[0]

    json_string = output.download_as_string()
    response = json_format.Parse(
        json_string, vision.types.AnnotateFileResponse())

    # The actual response for the first page of the input file.
    first_page_response = response.responses[0]
    annotation = first_page_response.full_text_annotation

 
    
    return annotation


def extract_permit (src_filename):

    #Compute and check if file has already been parsed and saved
    pre, ext = os.path.splitext(src_filename)
    dest_filename = pre +'.json'

    if os.path.isfile(dest_filename):
        print( dest_filename + ' already exists')
        return


    # Upload to bucket

    rand = binascii.b2a_hex(os.urandom(8)).decode()
    date = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    dest_name = f'gs://pdfparser-cloud-vision-upload/{date}-{rand}.pdf'
    print(subprocess.check_output([gsutil_path, 'cp', src_filename, dest_name], stderr=subprocess.STDOUT))
    dest_name
    
    results = async_detect_document(dest_name, dest_name + "-results")



    #initializing variables for loop
    wordspans = []

    #assemble_word(results.pages[0].blocks[2].paragraphs[0].words[0])
    for page in results.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    wordspans.append (pdfspan_from_word(word))

    global parser 
    parser = PdfParser(spans=wordspans)
  

    permit = {}
    permit['Building Address'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Building', 'Address', ':']),
                left_excluding=parser.find_sequence_as_span(['Building', 'Address', ':']), 
                right_excluding=parser.find_sequence_as_span(['Certificate', 'Number', ':']),
                bottom_excluding=parser.find_sequence_as_span(['Parcel', 'ID', ':'])))


    permit['Certificate Number'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Certificate', 'Number', ':']),
                left_excluding=parser.find_sequence_as_span(['Certificate', 'Number', ':']), 
                bottom_excluding=parser.find_sequence_as_span(['Date', 'Issued', ':'])))

    try:
        wardspan = parser.find_sequence_as_span(['Ward', '#', ':'])
    except:
        wardspan = parser.find_sequence_as_span(['Ward'])

    permit['Parcel ID'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Parcel', 'ID', ':']),
                left_excluding=parser.find_sequence_as_span(['Parcel', 'ID', ':']), 
                right_excluding=wardspan,
                bottom_excluding=parser.find_sequence_as_span(['Permitted', 'Occupancy', ':'])))

    permit['Ward #'] = parser.extract_text(parser.box(
                top_including=wardspan,
                left_excluding=wardspan, 
                right_excluding=parser.find_sequence_as_span(['Date', 'Issued', ':']),
                bottom_excluding=parser.find_sequence_as_span(['Permitted', 'Occupancy', ':'])))

    permit['Date Issued'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Date', 'Issued', ':']),
                left_excluding=parser.find_sequence_as_span(['Date', 'Issued', ':']),
                bottom_excluding=parser.find_sequence_as_span(['Permitted', 'Occupancy', ':'])))

    permit['Permitted Occupancy'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Permitted', 'Occupancy', ':']),
                left_excluding=parser.find_sequence_as_span(['Permitted', 'Occupancy', ':']), 
                bottom_excluding=parser.find_sequence_as_span(['Zoning', 'Use', 'Type', ':'])))

    try:
        zoneapprovalspan = parser.find_sequence_as_span(['Zoning', 'Approval', ':'])
    except:
        zoneapprovalspan = parser.find_sequence_as_span(['Zoning', 'Approval'])            

    permit['Zoning Use Type'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Zoning', 'Use', 'Type', ':']),
                left_excluding=parser.find_sequence_as_span(['Zoning', 'Use', 'Type', ':']), 
                bottom_excluding=zoneapprovalspan))

    permit['Zoning Approval'] = parser.extract_text(parser.box(
                top_including=zoneapprovalspan,
                left_excluding=zoneapprovalspan, 
                bottom_excluding=parser.find_sequence_as_span(['Applicable', 'Building', 'Code', ':'])))

    permit['Applicable Building Code'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Applicable', 'Building', 'Code', ':']),
                left_excluding=parser.find_sequence_as_span(['Applicable', 'Building', 'Code', ':']), 
                right_excluding=parser.find_sequence_as_span(['Permit', 'Number', ':']),
                bottom_excluding=parser.find_sequence_as_span(['Construction', 'Type', ':'])))

    permit['Permit Number'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Permit', 'Number', ':']),
                left_excluding=parser.find_sequence_as_span(['Permit', 'Number', ':']), 
                bottom_excluding=parser.find_sequence_as_span(['Final', 'Inspection', 'Date', ':'])))

    permit['Construction Type'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Construction', 'Type', ':']),
                left_excluding=parser.find_sequence_as_span(['Construction', 'Type', ':']), 
                right_excluding=parser.find_sequence_as_span(['Final', 'Inspection', 'Date', ':']),
                bottom_excluding=parser.find_sequence_as_span(['Use', 'Group', '(', 's', ')', ':'])))

    permit['Final Inspection Date'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Final', 'Inspection', 'Date', ':']),
                left_excluding=parser.find_sequence_as_span(['Final', 'Inspection', 'Date', ':']), 
                bottom_excluding=parser.find_sequence_as_span(['Building', 'Sprinkler', 'System', ':'])))

    permit['Use Group(s)'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Use', 'Group', '(', 's', ')', ':']),
                left_excluding=parser.find_sequence_as_span(['Use', 'Group', '(', 's', ')', ':']), 
                right_excluding=parser.find_sequence_as_span(['Building', 'Sprinkler', 'System', ':']),
                bottom_excluding=parser.find_sequence_as_span(['Conditions', ':'])))

    permit['Building Sprinkler System'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Building', 'Sprinkler', 'System', ':']),
                left_excluding=parser.find_sequence_as_span(['Building', 'Sprinkler', 'System', ':']), 
                bottom_excluding=parser.find_sequence_as_span(['Conditions', ':'])))

    permit['Conditions'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Conditions', ':']),
                left_excluding=parser.find_sequence_as_span(['Conditions', ':']), 
                bottom_excluding=parser.find_sequence_as_span(['Property', 'Owner', ':'])))

    permit['Property Owner'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Property', 'Owner', ':']),
                left_excluding=parser.find_sequence_as_span(['Property', 'Owner', ':']), 
                right_excluding=parser.find_sequence_as_span(['Lessee', ':']),
                bottom_excluding=parser.find_sequence_as_span(['Permission', 'is', 'hereby', 'granted'])))

    permit['Lessee'] = parser.extract_text(parser.box(
                top_including=parser.find_sequence_as_span(['Lessee', ':']),
                left_excluding=parser.find_sequence_as_span(['Lessee', ':']), 
                bottom_excluding=parser.find_sequence_as_span(['Permission', 'is', 'hereby', 'granted'])))


    
    with open(dest_filename, 'w') as outfile:
        json.dump(permit, outfile, indent=4)
    print('Wrote json to', dest_filename)
# %%
extract_permit('permit-tests/CERTIFICATES_OF_OCCUPANCY_-_OOP-2020-02394_-_622_N_HOMEWOOD_AVE.pdf')



# %%
PDF_list = glob.glob('C:\\Users\\Nadz\\Documents\\Learning\\CreateLab\\Occupany Permits\\2020\\*.pdf')

for PDF in PDF_list:
    print('Extracting contents from ' + PDF)
    extract_permit(PDF)

#%%
extract_permit(PDF)
# %%
parser.find_sequence_as_span(['Use', 'Group', '(', 's', ')', ':'])
# %%
parser.first_row()
# %%
row = parser.first_row()
while row:
    for span in parser.spans_from_row(row):
        print(span.text, end=' ')
    print()
    nextrow = parser.next_row(row)
    if nextrow == row:
        break
    row = nextrow
# %%
