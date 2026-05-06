// =====================================================================
// Biofilm Quantitative Analysis - Fiji/ImageJ Macro
// =====================================================================
// Method:
//   1. Compute B/(R+G+B) blue ratio for every pixel
//   2. Otsu auto-threshold per image, floored at blank's P90
//   3. Mask biofilm-positive regions, draw red outlines
//   4. Output: annotated images + CSV with area / blue ratio / integrated density
//
// Usage:
//   In Fiji: File → Open → select this macro → Run
//   You will be prompted for input/output directories.
// =====================================================================

#@ File dataDir (value="") style="directory" label="Biofilm images directory"
#@ File outputDir (value="") style="directory" label="Output directory (create if needed)"
#@ String blankFile (value="34.png") label="Blank control filename"

dataPath = dataDir.getAbsolutePath();
outPath = outputDir.getAbsolutePath();
minRegionSize = 30;
floorPercentile = 90;        // Default percentile floor

if (!File.exists(outPath))
    File.makeDirectory(outPath);

// ===== Step 1: Compute blank P90 =====
blankPath = dataPath + File.separator + blankFile;
open(blankPath);
blankTitle = getTitle();
if (nChannels > 3) run("RGB Color");

run("Split Channels");
redBlank = "C1-" + blankTitle;
greenBlank = "C2-" + blankTitle;
blueBlank = "C3-" + blankTitle;

// B/(R+G+B)
imageCalculator("Add create 32-bit", redBlank, greenBlank);
tmp = getTitle();
imageCalculator("Add create 32-bit", tmp, blueBlank); close(tmp);
denom = getTitle();
imageCalculator("Divide create 32-bit", blueBlank, denom); close(denom);
ratioImg = getTitle();

// Background mask
selectWindow(blueBlank);
setAutoThreshold("Default");
run("Create Mask");
bgMask = getTitle();

// Measure P90
selectWindow(ratioImg);
run("Histogram");
getHistogram(hist, bins);
totalCount = 0;
for (i = 0; i < hist.length; i++) totalCount += hist[i];
cum = 0;
p90 = bins[hist.length-1];
for (i = 0; i < hist.length; i++) {
    cum += hist[i];
    if (cum >= totalCount * floorPercentile / 100.0) {
        p90 = bins[i];
        break;
    }
}
threshold_p90 = p90;

print("Blank: " + blankFile + "  P" + floorPercentile + " = " + threshold_p90);

close(redBlank); close(greenBlank); close(blueBlank);
close(blankTitle); close(denom); close(ratioImg); close(bgMask);
roiManager("Reset");

// ===== Step 2: Process each image =====
fileList = getFileList(dataPath);
Array.sort(fileList);
n = 0;

for (i = 0; i < fileList.length; i++) {
    fn = fileList[i];
    if (startsWith(fn, ".")) continue;
    if (!endsWith(fn, ".png") && !endsWith(fn, ".jpg")) continue;
    if (fn == blankFile) continue;

    print("Processing: " + fn);
    open(dataPath + File.separator + fn);
    imgTitle = getTitle();
    if (nChannels > 3) run("RGB Color");

    run("Split Channels");
    redCh = "C1-" + imgTitle;
    greenCh = "C2-" + imgTitle;
    blueCh = "C3-" + imgTitle;

    // B/(R+G+B)
    imageCalculator("Add create 32-bit", redCh, greenCh);
    tmp = getTitle();
    imageCalculator("Add create 32-bit", tmp, blueCh); close(tmp);
    denom = getTitle();
    imageCalculator("Divide create 32-bit", blueCh, denom); close(denom);
    ratioImg = getTitle();

    // Background mask
    selectWindow(blueCh);
    setAutoThreshold("Default");
    run("Create Mask");
    bgMask = getTitle();

    // Otsu threshold
    selectWindow(ratioImg);
    setAutoThreshold("Otsu");
    run("Convert to Mask");
    otsuMask = getTitle();
    getThreshold(lower, upper);
    otsu_th = lower;

    final_th = maxOf(otsu_th, threshold_p90);

    // Apply final threshold
    selectWindow(ratioImg);
    setThreshold(final_th, 999);
    run("Convert to Mask");
    stainedMask = getTitle();
    imageCalculator("AND create", stainedMask, bgMask);
    finalMask = getTitle();
    close(stainedMask); close(bgMask);

    // Analyze Particles
    selectWindow(finalMask);
    run("Analyze Particles...",
        "size=" + minRegionSize + "-Infinity add");

    if (nResults > 0) {
        run("Measure");
        totalArea = getResult("Area", nResults - 1);

        selectWindow(ratioImg);
        run("Measure");
        meanBR = getResult("Mean", nResults);
        integratedBR = totalArea * meanBR;

        selectWindow(finalMask);
        run("Measure");
        wellArea = getResult("Area", nResults + 1);
        pct = totalArea / wellArea * 100;

        setResult("Filename", n, fn);
        setResult("Floor", n, "P" + floorPercentile);
        setResult("Final_Th", n, final_th);
        setResult("Area_pct", n, pct);
        setResult("Mean_BRatio", n, meanBR);
        setResult("Integrated_BR", n, integratedBR);
        n++;
    }

    // Draw red contours
    selectWindow(imgTitle);
    run("Duplicate...", "title=annotated_" + fn);
    run("From ROI Manager");
    setForegroundColor(255, 0, 0);
    setLineWidth(2);
    run("Draw");

    savePath = outPath + File.separator + fn;
    saveAs("PNG", savePath);

    close(redCh); close(greenCh); close(blueCh);
    close(ratioImg); close(finalMask);
    close(imgTitle);
    selectWindow("annotated_" + fn); close();
    roiManager("Reset");
}

if (n > 0) {
    csvPath = outPath + File.separator + "biofilm_results_Fiji.csv";
    saveAs("Results", csvPath);
    print("Results: " + csvPath + " (" + n + " images)");
}

print("Done!");
