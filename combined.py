import cv2
import math
import numpy as np
import pyautogui
import time

class combined:

    def __init__(self):
        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = False

        self.alreadyClicked = True
        self.clickCounter = 0

        # sets noise sensitivity level
        self.noiseSensitivity = 2

        # taken from PointTracker:
        self.mouseMode = True
        self.scrollMode = False
        self.clickMode = True
        #self.isHistCreated = False
        self.traversePoints = []
        screenSize = pyautogui.size()
        self.screenSizeX = screenSize[0]
        self.screenSizeY = screenSize[1]

        self.isHandHistCreated = False
        self.isBgCaptured = False
        self.bgSubThreshold = 30

        # Background subtractor learning rate
        self.bgSubtractorLr = 0

        self.xs = [6.0/20.0, 9.0/20.0, 12.0/20.0]
        self.ys = [9.0/20.0, 10.0/20.0, 11.0/20.0]

        # Gamma correction lookUpTable
        # Increase the contrast
        gamma = 1
        self.lookUpTable = np.empty((1,256), np.uint8)
        for i in range(256):
            self.lookUpTable[0,i] = np.clip(pow(i / 255.0, gamma) * 255.0, 0, 255)

    def createHandHistogram(self, frame):
        rows, cols, _ = frame.shape
        hsvFrame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        roi = np.zeros([180, 20, 3], dtype=hsvFrame.dtype)

        i = 0
        for x in self.xs:
            for y in self.ys:
                x0, y0 = int(x*rows), int(y*cols)+50
                roi[i*20:i*20 + 20, :, :] = hsvFrame[x0:x0 + 20, y0:y0 + 20, :]

                i += 1
        handHist = cv2.calcHist([roi], [0, 1], None, [180, 256], [0, 180, 0, 256])
        return cv2.normalize(handHist, handHist, 0, 255, cv2.NORM_MINMAX)

    def drawRect(self, frame):
        rows, cols, _ = frame.shape

        for x in self.xs:
            for y in self.ys:
                x0, y0 = int(x*rows), int(y*cols)+50
                cv2.rectangle(frame, (y0, x0), (y0 + 20, x0 + 20), (0, 255, 0), 1)

    def histMasking(self, frame, handHist):
        """Create the HSV masking"""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        dst = cv2.calcBackProject([hsv], [0, 1], handHist, [0, 180, 0, 256], 1)

        disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
        cv2.filter2D(dst, -1, disc, dst)

        ret, thresh = cv2.threshold(dst, 150, 255, cv2.THRESH_BINARY)

        kernel = np.ones((5, 5), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=7)
        # thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=5)
        # thresh = cv2.dilate(thresh, kernel, iterations=5)
        # thresh = cv2.erode(thresh, kernel, iterations=5)

        thresh = cv2.merge((thresh, thresh, thresh))
        return cv2.bitwise_and(frame, thresh)

    def getCentroid(self, contour):
        moment = cv2.moments(contour)
        if moment['m00'] != 0:
            cx = int(moment['m10']/moment['m00'])
            cy = int(moment['m01']/moment['m00'])
            return [cx, cy]
        else:
            return None

    def getMaxContours(self, contours):
        maxIndex = 0
        maxArea = 0

        for i in range(len(contours)):
            cnt = contours[i]
            area = cv2.contourArea(cnt)

            if area > maxArea:
                maxArea = area
                maxIndex = i
        return contours[maxIndex]

    def threshold(self, mask):
        grayMask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        ret, thresh = cv2.threshold(grayMask, 0, 255, 0)
        return thresh

    def bgSubMasking(self, frame):
        """Create a foreground (hand) mask
        @param frame: The video frame
        @return: A masked frame
        """
        fgmask = self.bgSubtractor.apply(frame, learningRate=self.bgSubtractorLr)

        kernel = np.ones((4, 4), np.uint8)
        # MORPH_OPEN removes noise
        # MORPH_CLOSE closes the holes in the object
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, kernel, iterations=2)
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_CLOSE, kernel, iterations=2)
        return cv2.bitwise_and(frame, frame, mask=fgmask)

    def getMaskAreaRatio(self, mask):
        grayMask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        ret, thresh = cv2.threshold(grayMask, 0, 255, 0)
        return np.sum(thresh)/(self.height*self.width*255)

    def setupFrame(self, frame_width, frame_height):
        """self.x0 and self.y0 are top left corner coordinates
        self.width and self.height are the width and height the ROI
        """
        x, y = 0.0, 0.4
        self.x0 = int(frame_width*x)
        self.y0 = 60 #int(frame_height*y)
        self.width = 300
        self.height = 350

    def countFingers(self, contour, contourAndHull):
        hull = cv2.convexHull(contour, returnPoints=False)
        if len(hull) > 3:
            defects = cv2.convexityDefects(contour, hull)
            cnt = 0
            if type(defects) != type(None):
                for i in range(defects.shape[0]):
                    s, e, f, d = defects[i, 0]
                    start = tuple(contour[s, 0])
                    end = tuple(contour[e, 0])
                    far = tuple(contour[f, 0])
                    angle = self.calculateAngle(far, start, end)

                    # Ignore the defects which are small and wide
                    # Probably not fingers
                    if d > 10000 and angle <= math.pi/2:
                        cnt += 1
                        cv2.circle(contourAndHull, far, 8, [255, 0, 0], -1)
            return True, cnt
        return False, 0

    def calculateAngle(self, far, start, end):
        """Cosine rule"""
        a = math.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
        b = math.sqrt((far[0] - start[0])**2 + (far[1] - start[1])**2)
        c = math.sqrt((end[0] - far[0])**2 + (end[1] - far[1])**2)
        angle = math.acos((b**2 + c**2 - a**2) / (2*b*c))
        return angle

    def execute(self, cnt, highestPoint, frame, righmostPoint, centroid):
        if self.mouseMode:
            targetX = highestPoint[0]
            targetY = highestPoint[1] - 100
            pyautogui.moveTo(targetX*self.screenSizeX/frame.shape[1] * 3, targetY*self.screenSizeY/frame.shape[0] * 3)
        if self.clickMode:
            if righmostPoint[0] is not None:
                verticalDistance =  centroid[1] - highestPoint[1]
                horizontalDistance = righmostPoint[0] - centroid[0]
                ratio = verticalDistance / horizontalDistance
                if ratio > 2:
                    if not self.alreadyClicked:
                        # sometimes a couple of clicks happen at the start which cause problems for me,
                        # try remove the if and see if it works for you
                        if self.clickCounter > 2:
                            print("Click")
                            pyautogui.click()
                        self.alreadyClicked = True
                        self.clickCounter += 1
                elif self.alreadyClicked:
                    self.alreadyClicked = False
        elif self.scrollMode:
            if len(self.traversePoints) >= 2:
                movedDistance = self.traversePoints[-1][1] - self.traversePoints[-2][1]
                pyautogui.scroll(-movedDistance/2)

    def detectHand(self, frame, handHist):
        roi = frame[self.y0:self.y0 + self.height,
                self.x0:self.x0 + self.width,
                :]

        roi = cv2.bilateralFilter(roi, 5, 50, 100)
        # Color masking
        histMask = self.histMasking(roi, handHist)
        cv2.imshow("histMask", histMask)

        # Background substraction
        bgSubMask = self.bgSubMasking(roi)
        cv2.imshow("bgSubMask", bgSubMask)

        # Attempt to learn the background automatically
        """
        areaRatio = self.getMaskAreaRatio(bgSubMask)
        if areaRatio > 0.6:
            self.bgSubtractorLr = 1
        elif areaRatio < 0.001:
            self.bgSubtractorLr = 0
        """

        # Overall mask
        mask = cv2.bitwise_and(histMask, bgSubMask)

        thresh = self.threshold(mask)
        cv2.imshow("Overall thresh", thresh)

        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        if len(contours) > 0:
            maxContour = self.getMaxContours(contours)

            c= max(contours, key=cv2.contourArea)
            # Draw contour and hull
            contourAndHull = np.zeros(roi.shape, np.uint8)
            hull = cv2.convexHull(maxContour)
            cv2.drawContours(contourAndHull, [maxContour], 0, (0, 255, 0), 2)
            cv2.drawContours(contourAndHull, [hull], 0, (0, 0, 255), 3)
            #extreme_top = tuple(hull[hull[:, :, 1].argmin()][0])
            highestPoint = maxContour[maxContour[:,:,1].argmin()][0]
            if highestPoint is not None:
                # Reduce noise in highestPoint
                if len(self.traversePoints) > 0:
                    if abs(highestPoint[0] - self.traversePoints[-1][0]) < self.noiseSensitivity:
                        highestPoint[0] = self.traversePoints[-1][0]
                    if abs(highestPoint[1] - self.traversePoints[-1][1]) < self.noiseSensitivity:
                        highestPoint[1] = self.traversePoints[-1][1]
                highestPoint[0] += self.x0
                highestPoint[1] += self.y0
                highestPoint = tuple(highestPoint)
                #print(highestPoint)

                cv2.circle(frame, highestPoint, 5, [0, 0, 255], -1)

                if len(self.traversePoints) < 10:
                    self.traversePoints.append(highestPoint)
                else:
                    self.traversePoints.pop(0)
                    self.traversePoints.append(highestPoint)

            found, cnt = self.countFingers(maxContour, contourAndHull)
            cv2.imshow("Contour and Hull", contourAndHull)


            centroid = self.getCentroid(maxContour)
            if centroid is not None:
                centroid[0] += self.x0
                centroid[1] += self.y0
                cv2.circle(frame, tuple(centroid), 5, [255, 0, 0], -1)

            #draw righmostPoint on the most right contour
            extRight = tuple(c[c[:, :, 0].argmax()][0])
            righmostPoint=(extRight[0] + self.x0, extRight[1] + self.y0)
            #print (centroid)
            #print ("centroid")
            #print (righmostPoint)
            #print ("righmostPoint")
            if extRight is not None and centroid is not None:
                cv2.circle(frame, righmostPoint, 5, [0, 0, 255], -1)

            if found:
                self.execute(cnt, highestPoint, frame, righmostPoint, centroid)


    def startDetecting(self):
        start_time = time.perf_counter()
        has_captured = False
        wait_for_hand_in_box = False
        cap = cv2.VideoCapture(0)
        font = cv2.FONT_HERSHEY_SIMPLEX
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.setupFrame(frame_width, frame_height)

        while cap.isOpened():
            ret, frame = cap.read()
            frame = cv2.flip(frame, 1)
            cap.set(10, 200  ) # brightness     min: 0   , max: 255 , increment:1

            # Increase the contrast
            # frame = cv2.convertScaleAbs(frame, alpha=3, beta=-500)

            # Gamma corection
            # Increase the contrast
            frame = cv2.LUT(frame, self.lookUpTable)

            cv2.rectangle(frame, (self.x0, self.y0), (self.x0 + self.width - 1, self.y0 + self.height - 1), (255, 0, 0), 2)

            k = cv2.waitKey(1) & 0xFF
            if(not has_captured):
                time_rem = 12-(time.perf_counter()-start_time)
                if(time_rem >= 0):
                    cv2.putText(frame, "Align hand: " + str(int(time_rem)),(10,42), font, 1, (0,0,255), 2, cv2.LINE_AA)
                else:
                   self.isHandHistCreated = True
                   handHist = self.createHandHistogram(frame)
                   has_captured = True
                   wait_for_hand_in_box = True
            elif(wait_for_hand_in_box):
                time_rem = 17-(time.perf_counter()-start_time)
                if(time_rem >= 0):
                    cv2.putText(frame, "Make sure nothing in box: " + str(int(time_rem)),(10,42), font, 1, (0,0,255), 2, cv2.LINE_AA)
                else:
                    self.bgSubtractor = cv2.createBackgroundSubtractorMOG2(10, self.bgSubThreshold)
                    self.isBgCaptured = True
                    wait_for_hand_in_box = False

            if k == ord("z"):
                self.isHandHistCreated = True
                handHist = self.createHandHistogram(frame)
            elif k == ord('b'):
                self.bgSubtractor = cv2.createBackgroundSubtractorMOG2(10, self.bgSubThreshold)
                self.isBgCaptured = True

            elif k == ord("r"):
                self.bgSubtractor = None
                self.isBgCaptured = False

            if self.isHandHistCreated and self.isBgCaptured:
                self.detectHand(frame, handHist)
            elif not self.isHandHistCreated:
                self.drawRect(frame)

            cv2.imshow("Output", frame)
            if k == ord("q"):
                break
            elif k == ord("j"):
                self.y0 = min(self.y0 + 20, frame_height - self.height)
            elif k == ord("k"):
                self.y0 = max(self.y0 - 20, 0)
            elif k == ord("h"):
                self.x0 = max(self.x0 - 20, 0)
            elif k == ord("l"):
                self.x0 = min(self.x0 + 20, frame_width - self.width)

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    detector = combined()
    detector.startDetecting()
