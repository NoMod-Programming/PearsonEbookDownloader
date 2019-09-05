window.onload = function(){
  'use strict';

  const corsProxy = "https://crossorigin-originchanger.herokuapp.com/"
  const metadataUrl = "http://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getbookinfov2?bookid={bookid}&outputformat=JSON"
  const pageInfoUrl = "http://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getpagedetails?bookid={bookid}&bookeditionid={bookeditionid}&userroleid=2&ispreview=Y"
  const pdfPageUrl = "http://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getpdfpage?globalbookid={bookid}&pdfpage={pdfpage}&iscover={iscover}&ispreview=Y"
  const bookmarkInfoUrl = "http://auth.ebookplus.pearsoncmg.com/ebook/pdfplayer/getbaskettocinfo?userroleid=2&bookid={bookid}&language=en_US&bookeditionid={bookeditionid}&basket=all&ispreview=Y&scenarioid=1001"


  const arabicRegex = /^(.*?)(\d+)/gm;
  const romanRegex = /^(.*?)((?:(M{1,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})|M{0,4}(CM|C?D|D?C{1,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})|M{0,4}(CM|CD|D?C{0,3})(XC|X?L|L?X{1,3})(IX|IV|V?I{0,3})|M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|I?V|V?I{1,3})))+)$/gmi


  var bookId;
  var bookEditionId;
  var globalBookId;
  var pdfCoverArt;


  function hsidUrl(url) {
    var hsid = CryptoJS.MD5("ipadsecuretext" + url.replace("https","http"));
    return url + "&hsid=" + hsid;
  }


  const browserSavePdf = (function() {
    var a = document.createElement("a");
    document.body.appendChild(a);
    a.style = "display: none";
    return function(data, filename) {
      const blob = new Blob([data], {type:'application/pdf'});
      const url = window.URL.createObjectURL(blob);
      a.href = url;
      a.download = filename;
      a.click();
      window.URL.revokeObjectURL(url);
    }
  })();


  function getPageUrl(pdfPath, isCover) {
    isCover = isCover || "N";
    var pdfPath = pdfPath.replace("/assets/","");
    var pdfPage = pdfPageUrl.replace("{bookid}", globalBookId);
    pdfPage = pdfPage.replace("{pdfpage}", pdfPath);
    pdfPage = pdfPage.replace("{iscover}", isCover);
    return hsidUrl(pdfPage);
  }


  async function mergePdfs(pdfsToMerge) {
    const mergedPdf = await PDFLib.PDFDocument.create();
    for (const pdf of pdfsToMerge) {
      const copiedPages = await mergedPdf.copyPages(pdf, pdf.getPageIndices());
      copiedPages.forEach((page) => {
        mergedPdf.addPage(page);
      });
    }
    return mergedPdf;
  }


  const getPageRefs = (pdfDoc) => {
    const refs = [];
    pdfDoc.catalog.Pages().traverse((kid, ref) => {
      refs.push(ref); // Everything's a page!
    });
    return refs;
  }


  async function downloadPdfPages(pdfPageInfo) {

    var textarea = document.getElementById("downloadStatus");

    textarea.value = "Downloading pages...\n";

    const coverBuffer = await fetch(corsProxy + getPageUrl(pdfCoverArt, "Y"), {
      headers: {
        'x-requested-with':'pearsonEbookDownloader',
        'cors-origin-set':'https://etext.pearson.com',
      }
    }).then((res) => res.arrayBuffer());
    const coverPdf = await PDFLib.PDFDocument.load(coverBuffer);

    textarea.value += "Downloaded cover\n"

    var pdfPages = [[0, coverPdf]];
    var pdfPageTable = {};
    var reversePdfPageTable = {}; // Used for bookmarks

    var i = 0;
    var pagePromises = function() {
      if (i < pdfPageInfo.length) {
        textarea.value += "Downloading page " + (i + 1) + " of " + pdfPageInfo.length + "\n";
        textarea.scrollTop = textarea.scrollHeight;
        let j = i; // Save it in this scope
        i++;
        return new Promise(async function(resolve, reject) {
          pdfPageTable[pdfPageInfo[j].pageOrder] = pdfPageInfo[j].bookPageNumber;
          reversePdfPageTable[pdfPageInfo[j].bookPageNumber] = pdfPageInfo[j].pageOrder;
          var pdfBuffer = await fetch(corsProxy + getPageUrl(pdfPageInfo[j].pdfPath), {
            headers: {
              'x-requested-with':'pearsonEbookDownloader',
              'cors-origin-set':'https://etext.pearson.com',
            }
          }).then((res) => res.arrayBuffer());
          const pdfDoc = await PDFLib.PDFDocument.load(pdfBuffer);
          pdfPages.push([j + 1,pdfDoc]);
          resolve();
        });
      } else {
        return null;
      }
    }

    var pool = new PromisePool(pagePromises, 40);
    await pool.start();

    textarea.value += "Merging pages...\n";
    textarea.scrollTop = textarea.scrollHeight;

    pdfPages.sort((a,b)=>(a[0] - b[0]));
    pdfPages = pdfPages.map((item)=>item[1]);
    var mergedPdf = await mergePdfs(pdfPages);
    window.mergedPdf = mergedPdf;

    textarea.value += "Fixing metadata...\n";
    textarea.scrollTop = textarea.scrollHeight;

    /* Fix page labels */
    var labels = PDFLib.PDFArray.withContext(mergedPdf.context);
    labels.push(PDFLib.PDFNumber.of(0));
    labels.push(PDFLib.PDFDict.fromMapWithContext(
      new Map([[
        (PDFLib.PDFName.of('P')),
        PDFLib.PDFString.of('(cover)')
      ]]),
      mergedPdf.context,
    ));

    var lastMode = null;
    var lastPrefix = "";
    for (var pageNumber in pdfPageTable) {
      let pageLabel = pdfPageTable[pageNumber];

      let currMode = null;
      let prefix = "";
      let style = PDFLib.PDFDict.withContext(mergedPdf.context);
      if (arabicRegex.exec(pageLabel) !== null) {
        currMode = "arabic";
        arabicRegex.lastIndex = 0;
        prefix = arabicRegex.exec(pageLabel)[1];
        style.set(PDFLib.PDFName.of('S'), PDFLib.PDFName.of('D'));
      } else if (romanRegex.exec(pageLabel) !== null) {
        currMode = "roman";
        romanRegex.lastIndex = 0;
        prefix = romanRegex.exec(pageLabel)[1];
        style.set(PDFLib.PDFName.of('S'), PDFLib.PDFName.of('r'));
      }
      arabicRegex.lastIndex = 0;
      romanRegex.lastIndex = 0;

      if (currMode !== lastMode || prefix !== lastPrefix) {
        if (prefix !== "") {
          style.set(PDFLib.PDFName.of('P'), PDFLib.PDFName.of('(' + prefix + ')'));
        }
        labels.push(PDFLib.PDFNumber.of(pageNumber));
        labels.push(style);
        lastMode = currMode;
        lastPrefix = prefix;
      }
    }

    mergedPdf.catalog.set(PDFLib.PDFName.of('PageLabels'), 
    PDFLib.PDFDict.fromMapWithContext(
      new Map([[
        (PDFLib.PDFName.of('Nums')),
        labels
      ]]),
      mergedPdf.context,
    ));

    /* Add bookmarks */
    var bookmarkUrl = bookmarkInfoUrl.replace("{bookid}", bookId);
    bookmarkUrl = bookmarkUrl.replace("{bookeditionid}", bookEditionId);
    var bookmarkData = await fetch(corsProxy + hsidUrl(bookmarkUrl), {
      headers: {
        'x-requested-with':'pearsonEbookDownloader',
        'cors-origin-set':'https://etext.pearson.com',
      }
    }).then((res) => res.json());

    const pageRefs = getPageRefs(mergedPdf);
    
    function recursiveSetBookmarks(bookmarkDict, parent) {
      if (parent === undefined) {
        var parent = PDFLib.PDFNull;
      }
      if (!Array.isArray(bookmarkDict)) {
        var bookmarkDict = [bookmarkDict];
      }
      let bookmarks = [];
      let count = 0;
      for (var bookmarkData in bookmarkDict) {
        var bookmarkData = bookmarkDict[bookmarkData];
        let bookmarkName = bookmarkData['n']; // Name of the section
        let pageNum = reversePdfPageTable[bookmarkData['lv']['content'].toString()]; // First page of the section

        let latestBookmarkRef = mergedPdf.context.nextRef();

        // Actually make the bookmark here
        let destArray = mergedPdf.context.obj([
          pageRefs[pageNum], // Might be off by 1
          PDFLib.PDFName.of("XYZ"),
          PDFLib.PDFNull,
          PDFLib.PDFNull,
          PDFLib.PDFNull,
        ]);

        let bookmark = PDFLib.PDFDict.fromMapWithContext(
          new Map([
            [PDFLib.PDFName.of('Title'), PDFLib.PDFString.of(bookmarkName)],
            [PDFLib.PDFName.of('Parent'), parent],
            [PDFLib.PDFName.of('Dest'), destArray],
          ]),
          mergedPdf.context,
        );

        mergedPdf.context.assign(latestBookmarkRef, bookmark);

        bookmarks.push([latestBookmarkRef, bookmark]);

        let childBookmarks = [];
        let childCount = 0;
        if (bookmarkData.hasOwnProperty('be')) {
          [childBookmarks, childCount] = recursiveSetBookmarks(bookmarkData['be'], latestBookmarkRef);

          // Since we have children, make sure that their "Prev" and "Next" are set
          // And set our own "First" and "Last" items
          let previousChild;
          for (let i = 0; i < childBookmarks.length; i++) {
            let cbookmark = childBookmarks[i];
            if (i > 0) cbookmark[1].set(PDFLib.PDFName.of('Prev'), previousChild);
            cbookmark[1].set(PDFLib.PDFName.of('Parent'), latestBookmarkRef);
            if (i < childBookmarks.length - 1) cbookmark[1].set(PDFLib.PDFName.of('Next'), childBookmarks[i+1][0]);
            previousChild = cbookmark[0];
          }

          bookmark.set(PDFLib.PDFName.of('First'), childBookmarks[0][0]);
          bookmark.set(PDFLib.PDFName.of('Last'), childBookmarks[childBookmarks.length - 1][0])
        }
        bookmark.set(PDFLib.PDFName.of('Count'), PDFLib.PDFNumber.of(childCount + childBookmarks.length));
        count += childCount + childBookmarks.length + 1;
      }
      return [bookmarks, count];
    }

    let coverBookmark = mergedPdf.context.nextRef();
    let outlineRef = mergedPdf.context.nextRef();

    // Actually make the bookmark here
    let destArray = mergedPdf.context.obj([
      pageRefs[0], // First page, aka the cover
      PDFLib.PDFName.of("XYZ"),
      PDFLib.PDFNull,
      PDFLib.PDFNull,
      PDFLib.PDFNull,
    ]);

    let cbookmark = PDFLib.PDFDict.fromMapWithContext(
      new Map([
        [PDFLib.PDFName.of('Title'), PDFLib.PDFString.of('(cover)')],
        [PDFLib.PDFName.of('Parent'), outlineRef],
        [PDFLib.PDFName.of('Dest'), destArray],
      ]),
      mergedPdf.context,
    );

    mergedPdf.context.assign(coverBookmark, cbookmark);
    
    let [topLevelBookmarks, count] = recursiveSetBookmarks(bookmarkData[0]['basketsInfoTOList'][0]['document'][0]['bc']['b']['be'], outlineRef);

    let lastBookmark;
    if (count > 0) {
      cbookmark.set(PDFLib.PDFName.of('Next'), topLevelBookmarks[0][0])
      lastBookmark = topLevelBookmarks[topLevelBookmarks.length - 1][0];
    } else {
      lastBookmark = coverBookmark;
    }

    let outline = PDFLib.PDFDict.fromMapWithContext(
      new Map([
        [PDFLib.PDFName.of('Type'), PDFLib.PDFName.of('Outlines')],
        [PDFLib.PDFName.of('First'), coverBookmark],
        [PDFLib.PDFName.of('Last'), lastBookmark],
        [PDFLib.PDFName.of('Count'), PDFLib.PDFNumber.of(topLevelBookmarks.length + count)]
      ]),
      mergedPdf.context,
    );
    mergedPdf.context.assign(outlineRef, outline);

    mergedPdf.catalog.set(PDFLib.PDFName.of('Outlines'), outlineRef);

    let previousChild;
    for (let i = 0; i < topLevelBookmarks.length; i++) {
      let bookmark = topLevelBookmarks[i];
      if (i > 0) bookmark[1].set(PDFLib.PDFName.of('Prev'), previousChild);
      if (i < topLevelBookmarks.length - 1) bookmark[1].set(PDFLib.PDFName.of('Next'), topLevelBookmarks[i+1][0]);
      previousChild = bookmark[0];
    }

    textarea.value += "Writing out PDF... This may take a while\n";
    textarea.scrollTop = textarea.scrollHeight;
    const pdfBytes = await mergedPdf.save();

    browserSavePdf(pdfBytes, bookId + ".pdf");
  }


  function getPageInfo(userBook) {

    globalBookId = userBook["globalBookID"];
    bookEditionId = userBook["bookEditionID"];
    pdfCoverArt = userBook["pdfCoverArt"];

    var requestUrl = pageInfoUrl.replace("{bookid}", userBook["bookID"]);
    requestUrl = requestUrl.replace("{bookeditionid}", bookEditionId);
    requestUrl = hsidUrl(requestUrl);

    fetch(corsProxy + requestUrl, {
      headers: {
        'x-requested-with':'pearsonEbookDownloader',
        'cors-origin-set':'https://etext.pearson.com',
      }
    })
    .then(function(response) {
      response.text().then(function(val) {
        document.getElementById("pageInfo").value = val;
        downloadPdfPages(JSON.parse(val)[0]['pdfPlayerPageInfoTOList'])
      });
    })
    .catch(error => console.error(error));
  }


  window.doDownload = function() {
    bookId = document.getElementById("bookid").value;
    var requestUrl = metadataUrl.replace("{bookid}", bookId);
    requestUrl = hsidUrl(requestUrl);

    fetch(corsProxy + requestUrl, {
      headers: {
        'x-requested-with':'pearsonEbookDownloader',
        'cors-origin-set': 'https://etext.pearson.com',
      }
    })
    .then(function(response) {
      response.text().then(function(val) {
        document.getElementById("bookInfo").value = val;
        getPageInfo(JSON.parse(val)[0]["userBookTOList"][0]);
      });
    })
    .catch(error => console.error(error));
  }

}