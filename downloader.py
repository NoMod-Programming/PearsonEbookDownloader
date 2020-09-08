#! /usr/bin/env python3
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

import urllib.parse
import tempfile
import json
import urllib.request
import hashlib
import os
import sys
import time
import re

from PyPDF2 import PdfFileWriter, PdfFileReader
from PyPDF2.generic import NameObject, DictionaryObject, ArrayObject, NumberObject

from multiprocessing.pool import ThreadPool

language = "en_US"
roletypeid = 2 # 3 for instructor, though the server doesn't seem to care

# Make their server think this is a regular book request
handler = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(handler)
opener.addheaders = [("Origin","https://etext.pearson.com")]
urllib.request.install_opener(opener)

arabicRegex = re.compile(r"^(?P<prefix>.*?)(\d+)$")
romanRegex = re.compile(r"^(?P<prefix>.*?)((?:(M{1,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})|M{0,4}(CM|C?D|D?C{1,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})|M{0,4}(CM|CD|D?C{0,3})(XC|X?L|L?X{1,3})(IX|IV|V?I{0,3})|M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|I?V|V?I{1,3})))+)$", re.IGNORECASE)

# Some interesting parts of the books js code:
#
# MD5_SECRET_KEY: "ipadsecuretext"
# Dear Pearson,
#   Please don't consider MD5 a "secure" algorithm by any means.
# Sincerely,
# Everybody that looks at your horrifying code
#
# UserRoleType: {
#     Student: 2,
#     Instructor: 3,
# }
# The above corresponds to the `roletypeid` GET parameter in a lot pf the requests
# Surprisingly, it's not checked at any point to see if, say, a student is impersonating
# a teacher, even though the API throws out an error if it is omited.
#
# Also, since it's there, a good TODO would be to download other types of media along with the PDF.
# Should be relatively simple.

bookInfoUrl = "http://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getbookinfov2?bookid={}&outputformat=JSON"
pageInfoUrl = "https://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getpagedetails?bookid={bookid}&bookeditionid={bookeditionid}&userroleid={userroleid}&ispreview=Y"
pdfUrl = "https://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getpdfpage?globalbookid={bookid}&pdfpage={pdfpage}&iscover={iscover}&ispreview=Y"
bookmarkInfoUrl = "https://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getbaskettocinfo?userroleid={userroleid}&bookid={bookid}&language={language}&bookeditionid={bookeditionid}&basket=all&ispreview=Y&scenarioid={scenarioid}"

def hsidUrl(aUrl):
    # Append this url's "hsid" to it (md5 hash of its http url)
    md5Hasher = hashlib.new("md5")
    md5Hasher.update(b"ipadsecuretext")
    md5Hasher.update(aUrl.replace("https://","http://").encode("utf-8"))
    return aUrl + "&hsid=" + md5Hasher.hexdigest()

def main(bookId):
    if bookId.startswith("http"):
        print("Trying to extract bookId from url")
        bookData = urllib.parse.parse_qs(bookId.split("?")[-1])
        if (bookData.get("values", None)) is not None:
            bookData = {
                itemName : [itemValue] for itemName, itemValue in
                zip(*[iter(bookData["values"][0].split("::"))]*2)
            }
            # Fix capitalization
            bookData["bookid"] = bookData["bookID"]
        bookId = bookData["bookid"][0]

    bookId = int(bookId)
    print("Downloading book id {}. Please open an issue on GitHub if this book id is incorrect.".format(bookId))

    print("Downloading metadata and eText information...")

    bookInfoGetUrl = bookInfoUrl.format(bookId)
    #print(hsidUrl(bookInfoGetUrl))
    with urllib.request.urlopen(hsidUrl(bookInfoGetUrl)) as bookInfoRequest:
        str_response = bookInfoRequest.read().decode('utf-8')
        bookInfo = json.loads(str_response)
        bookInfo = bookInfo[0]['userBookTOList'][0]

    pageInfoGetUrl = pageInfoUrl.format(
        userroleid=roletypeid,
        bookid=bookId,
        bookeditionid=bookInfo['bookEditionID']
        )
    with urllib.request.urlopen(hsidUrl(pageInfoGetUrl)) as pageInfoRequest:
        pageInfo = json.loads(pageInfoRequest.read().decode('utf-8'))
        pageInfo = pageInfo[0]['pdfPlayerPageInfoTOList']

    def getPageUrl(pdfPage, isCover="N"):
        pdfPage = pdfPage.replace("/assets/","")
        getPage = pagePath = pdfUrl.format(
            bookid=bookInfo['globalBookID'],
            pdfpage=pdfPage,
            iscover=isCover
        )
        return hsidUrl(getPage)


    with tempfile.TemporaryDirectory() as pdfDownloadDir:
        # Use a temporary directory to download all the pdf files to
        # First, download the cover file
        pdfPageTable = {}

        pdfPageLabelTable = {}

        urllib.request.urlretrieve(getPageUrl(bookInfo['pdfCoverArt'], isCover="Y"), os.path.join(pdfDownloadDir, "0000 - cover.pdf"))
        # Then, download all the individual pages for the e-book
        def download(pdfPage):
            pdfPageTable[pdfPage['bookPageNumber']] = pdfPage['pageOrder']
            savePath = os.path.join(pdfDownloadDir, "{:04} - {}.pdf".format(pdfPage['pageOrder'], pdfPage['bookPageNumber']))
            urllib.request.urlretrieve(getPageUrl(pdfPage['pdfPath']), savePath)

        threadPool = ThreadPool(40) # 40 threads should download a book fairly quickly
        print("Downloading pages to \"{}\"...".format(pdfDownloadDir))
        threadPool.map(download, pageInfo)

        print("Assembling PDF...")

        # Begin to assemble the final PDF, first by adding all the pages
        fileMerger = PdfFileWriter()
        for pdfFile in sorted(os.listdir(pdfDownloadDir)):
            fileMerger.addPage(PdfFileReader(os.path.join(pdfDownloadDir, pdfFile)).getPage(0))

        # And then add all the bookmarks to the final PDF
        bookmarkInfoGetUrl = bookmarkInfoUrl.format(
            userroleid=roletypeid,
            bookid=bookId,
            language=language,
            bookeditionid=bookInfo['bookEditionID'],
            scenarioid=1001
            )

        bookmarksExist = True
            
        with urllib.request.urlopen(hsidUrl(bookmarkInfoGetUrl)) as bookmarkInfoRequest:
            try:
                bookmarkInfo = json.loads(bookmarkInfoRequest.read().decode('utf-8'))
                bookmarkInfo = bookmarkInfo[0]['basketsInfoTOList'][0]
            except Exception as e:
                bookmarksExist = False

        def recursiveSetBookmarks(aDict, parent=None):
            if isinstance(aDict, dict):
                aDict = [aDict]
            for bookmark in aDict:
                # These are the main bookmarks under this parent (or the whole document if parent is None)
                bookmarkName = bookmark['name'] # Name of the section
                pageNum = str(bookmark['linkvalue']['content']) # First page (in the pdf's format)

                latestBookmark = fileMerger.addBookmark(bookmarkName, pdfPageTable[pageNum], parent)

                if 'basketentry' in bookmark:
                    recursiveSetBookmarks(bookmark['basketentry'], latestBookmark)

        if bookmarksExist:
            print("Adding bookmarks...")
            fileMerger.addBookmark("Cover", 0) # Add a bookmark to the cover at the beginning
            recursiveSetBookmarks(bookmarkInfo['document'][0]['basketcollection']['basket']['basketentry'])
        else:
            print("Bookmarks don't exist for ID {}".format(bookId))
        print("Fixing metadata...")
        # Hack to fix metadata and page numbers:
        pdfPageLabelTable = [(v,k) for k,v in pdfPageTable.items()]
        pdfPageLabelTable = sorted(pdfPageLabelTable, key=(lambda x: int(x[0])))
        labels = ArrayObject([
            NameObject(0), DictionaryObject({NameObject("/P"): NameObject("(cover)")})
        ])
        lastMode = None
        lastPrefix = ""
        # Now we check to see the ranges where we have roman numerals or arabic numerals
        # The following code is not ideal for this, so I'd appreciate a PR with a better solution
        for pageNumber, pageLabel in pdfPageLabelTable:
            currMode = None
            prefix = ""
            style = DictionaryObject()
            if arabicRegex.match(pageLabel):
                currMode = "arabic"
                prefix = arabicRegex.match(pageLabel).group("prefix")
                style.update({NameObject("/S"): NameObject("/D")})
            elif romanRegex.match(pageLabel):
                currMode = "roman"
                prefix = romanRegex.match(pageLabel).group("prefix")
                style.update({NameObject("/S"): NameObject("/r")})
            if currMode != lastMode or prefix != lastPrefix:
                if prefix:
                    style.update({
                        NameObject("/P"): NameObject("({})".format(prefix))
                    })
                labels.extend([
                    NumberObject(pageNumber),
                    style,
                ])
                lastMode = currMode
                lastPrefix = prefix
        rootObj = fileMerger._root_object
        # Todo: Fix the weird page numbering bug
        pageLabels = DictionaryObject()
        #fileMerger._addObject(pageLabels)
        pageLabels.update({
            NameObject("/Nums"): ArrayObject(labels)
        })
        rootObj.update({
            NameObject("/PageLabels"): pageLabels
        })

        print("Writing PDF...")
        with open("{} - {}.pdf".format(bookId, bookInfo['title']).replace("/","").replace(":","_"), "wb") as outFile:
            fileMerger.write(outFile)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Missing url of eText or bookId!")
        sys.exit(0)
    main(sys.argv[1])
