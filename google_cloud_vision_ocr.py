#%%

# Using example from here:
# https://cloud.google.com/vision/docs/ocr
# (click on Python)

#  TODO
# download auth keys into keys/auth.json
# try api with scanned, and with digital pdf

# Point to our credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = f"{os.path.dirname(os.path.realpath(__file__))}/keys/rsargent-paid-cloud-vision-auth.json"

import binascii, datetime, os, subprocess

# Install with pip install google-cloud-vision
from google.cloud import vision
# Install with pip install google-cloud-storage
from google.cloud import storage

from pdfparser import PdfSpan
#%%

# For Randy's laptop
gsutil_path = '/Users/rsargent/google-cloud-sdk/bin/gsutil'


print('gsutil version:')
try:
    print(subprocess.check_output([gsutil_path, '--version']))
except Exception as e:
    print('Could not find gsutil executable.  Please install or change gsutil_path to point to it')
    print(e)

print('Be sure to run gcloud auth login the first time')


# We're using rsargent-paid google project
bucket_name = 'pdfparser-cloud-vision-upload'

src_filename = 'permit-tests/CERTIFICATES_OF_OCCUPANCY_-_BP-2020-00467_-_6010_PENN_AVE.pdf'

# Upload to bucket

rand = binascii.b2a_hex(os.urandom(8)).decode()
date = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
dest_name = f'gs://pdfparser-cloud-vision-upload/{date}-{rand}.pdf'
print(subprocess.check_output([gsutil_path, 'cp', src_filename, dest_name], stderr=subprocess.STDOUT))
dest_name
# %%
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

    # Here we print the full text from the first page.
    # The response contains more information:
    # annotation/pages/blocks/paragraphs/words/symbols
    # including confidence scores and bounding boxes
    print(u'Full text:\n{}'.format(
        annotation.text))
    
    return annotation

results = async_detect_document(dest_name, dest_name + "-results")
# %%
results
#%%
# "CERTIFICATE"
results.pages[0].blocks[2].paragraphs[0].words[0]
#%%
#results.pages[0].blocks[2].paragraphs[0].words[0].symbols[0]

def assemble_word(word):
    ret = ''
    for symbol in word.symbols:
        ret = ret + symbol.text
    return ret

def pdfspan_from_word(word):
    text = assemble_word(word)
    vertices = word.bounding_box.normalized_vertices
    return PdfSpan(x1=vertices[0].x*100, y1=vertices[0].y*100,
                   x2=vertices[2].x*100, y2=vertices[2].y*100,
                   text=text)

#assemble_word(results.pages[0].blocks[2].paragraphs[0].words[0])
for page in results.pages:
    for block in page.blocks:
        for paragraph in block.paragraphs:
            for word in paragraph.words:
                print(pdfspan_from_word(word))



# %%
import json
json.dumps(results)
# %%
results
results

# %%
