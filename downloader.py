#! /usr/bin/env python3
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

arabicRegex = re.compile(r"^(?P<prefix>.*?)(\d+)$")
romanRegex = re.compile(r"^(?P<prefix>.*?)((?:(M{1,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})|M{0,4}(CM|C?D|D?C{1,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})|M{0,4}(CM|CD|D?C{0,3})(XC|X?L|L?X{1,3})(IX|IV|V?I{0,3})|M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|I?V|V?I{1,3})))+)$", re.IGNORECASE)

bookInfoUrl = "http://view.ebookplus.pearsoncmg.com/ebook/pdfplayer/getbookinfov2?bookid={}&outputformat=JSON"
pageInfoUrl = "https://view.ebookplus.pearsoncmg.com/ebook/pdfplayer/getpagedetails?userid={userid}&userroleid={userroleid}&bookid={bookid}&bookeditionid={bookeditionid}&authkey={authkey}"
pdfUrl = "https://view.ebookplus.pearsoncmg.com/ebook/pdfplayer/getpdfpage?globalbookid={bookid}&pdfpage={pdfpage}&iscover={iscover}&authkey={authkey}"
bookmarkInfoUrl = "https://view.ebookplus.pearsoncmg.com/ebook/pdfplayer/getbaskettocinfo?userroleid={userroleid}&bookid={bookid}&language={language}&authkey={authkey}&bookeditionid={bookeditionid}&basket=all&scenarioid={scenarioid}&platformid=1001"

def hsidUrl(aUrl):
    # Append this url's "hsid" to it (md5 hash of its http url)
    md5Hasher = hashlib.new("md5")
    md5Hasher.update(b"ipadsecuretext")
    md5Hasher.update(aUrl.replace("https://","http://").encode("utf-8"))
    return aUrl + "&hsid=" + md5Hasher.hexdigest()

def main(eTextUrl):
    bookData = urllib.parse.parse_qs(eTextUrl.split("?")[-1])

    print("Downloading metadata and eText information...")

    bookInfoGetUrl = bookInfoUrl.format(bookData["bookid"][0])
    #print(hsidUrl(bookInfoGetUrl))
    with urllib.request.urlopen(hsidUrl(bookInfoGetUrl)) as bookInfoRequest:
        str_response = bookInfoRequest.read().decode('utf-8')
        bookInfo = json.loads(str_response)
        bookInfo = bookInfo[0]['userBookTOList'][0]

    pageInfoGetUrl = pageInfoUrl.format(
        userid=bookData['userid'][0],
        userroleid=bookData['roletypeid'][0],
        bookid=bookData['bookid'][0],
        bookeditionid=bookInfo['bookEditionID'],
        authkey=bookData['sessionid'][0],
        )
    with urllib.request.urlopen(hsidUrl(pageInfoGetUrl)) as pageInfoRequest:
        pageInfo = json.loads(pageInfoRequest.read().decode('utf-8'))
        pageInfo = pageInfo[0]['pdfPlayerPageInfoTOList']

    def getPageUrl(pdfPage, isCover="N"):
        pdfPage = pdfPage.replace("/assets/","")
        getPage = pagePath = pdfUrl.format(
            bookid=bookInfo['globalBookID'],
            pdfpage=pdfPage,
            iscover=isCover,
            authkey=bookData['sessionid'][0]
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
            userroleid=bookData['roletypeid'][0],
            bookid=bookData['bookid'][0],
            language=language,
            authkey=bookData['sessionid'][0],
            bookeditionid=bookInfo['bookEditionID'],
            scenarioid=bookData['scenario'][0],
            )
        with urllib.request.urlopen(hsidUrl(bookmarkInfoGetUrl)) as bookmarkInfoRequest:
            bookmarkInfo = json.loads(bookmarkInfoRequest.read().decode('utf-8'))
            bookmarkInfo = bookmarkInfo[0]['basketsInfoTOList'][0]

        def recursiveSetBookmarks(aDict, parent=None):
            for bookmark in aDict:
                # These are the main bookmarks under this parent (or the whole document if parent is None)
                bookmarkName = bookmark['n'] # Name of the section
                pageNum = str(bookmark['lv']['content']) # First page (in the pdf's format)

                latestBookmark = fileMerger.addBookmark(bookmarkName, pdfPageTable[pageNum], parent)

                if 'be' in bookmark:
                    recursiveSetBookmarks(bookmark['be'], latestBookmark)
        print("Adding bookmarks...")
        fileMerger.addBookmark("Cover", 0) # Add a bookmark to the cover at the beginning
        recursiveSetBookmarks(bookmarkInfo['document'][0]['bc']['b']['be'])
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
        with open("out.pdf", "wb") as outFile:
            fileMerger.write(outFile)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Missing url of eText!")
        sys.exit(0)
    main(sys.argv[1])
