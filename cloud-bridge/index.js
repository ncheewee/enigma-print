const express = require("express");
const cors = require("cors");
const mqtt = require("mqtt");
const crypto = require("crypto");

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 4777;

// --- JWT Decoder Helper ---
// Decodes a JWT token payload without external dependencies (resilient and fast)
function decodeJwt(token) {
  try {
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      Buffer.from(base64, "base64")
        .toString("utf8")
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch (err) {
    console.error("JWT Decode error:", err.message);
    return null;
  }
}

// --- REST Endpoint ---
app.post("/print-piece", async (req, res) => {
  const { email, password, code, serialNumber, gcode3mfUrl } = req.body;

  if (!email || !serialNumber || !gcode3mfUrl || (!password && !code)) {
    return res.status(400).json({
      ok: false,
      message: "Missing credentials (password or code), serial number, or target gcode3mfUrl details."
    });
  }

  const stages = [];
  try {
    // 1. Authenticate with Bambu Lab Cloud REST API
    stages.push("Authenticating with Bambu Cloud");
    let accessToken = null;

    if (code && code.trim()) {
      console.log(`[Cloud Bridge] Authenticating user: ${email} via 6-digit verification code: ${code}`);
      const verifyRes = await fetch("https://api.bambulab.com/v1/user-service/user/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account: email, code: code.trim() })
      });

      if (!verifyRes.ok) {
        throw new Error(`Verification code submission failed: HTTP ${verifyRes.status}`);
      }

      const verifyData = await verifyRes.json();
      if (!verifyData.success || !verifyData.accessToken) {
        throw new Error(verifyData.apiError || "Verification code rejected or expired.");
      }
      accessToken = verifyData.accessToken;
    } else {
      console.log(`[Cloud Bridge] Authenticating user: ${email} via password`);
      const loginRes = await fetch("https://api.bambulab.com/v1/user-service/user/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account: email, password: password, apiError: "" })
      });

      if (!loginRes.ok) {
        throw new Error(`Login failed with HTTP status ${loginRes.status}`);
      }

      const loginData = await loginRes.json();

      // Check if 2FA/verification code is required
      if (loginData.loginType === "verifyCode") {
        throw new Error("Verification code sent to email! Please enter the 6-digit code in Settings.");
      }

      if (!loginData.success || !loginData.accessToken) {
        throw new Error(loginData.apiError || "Invalid account credentials or authentication rejected.");
      }
      accessToken = loginData.accessToken;
    }

    // 2. Obtain numeric uid from JWT or API Preference fallback
    stages.push("Resolving User preference details");
    let uid = null;
    const decoded = decodeJwt(accessToken);
    if (decoded && decoded.userId) {
      uid = decoded.userId;
    } else if (decoded && decoded.uid) {
      uid = decoded.uid;
    } else if (decoded && decoded.sub) {
      uid = decoded.sub;
    }

    if (!uid) {
      console.log("[Cloud Bridge] Fallback to design preferences endpoint to retrieve UID...");
      const prefRes = await fetch("https://api.bambulab.com/v1/design-user-service/my/preference", {
        headers: { "Authorization": `Bearer ${accessToken}` }
      });
      if (prefRes.ok) {
        const prefData = await prefRes.json();
        uid = prefData.uid || prefData.userId;
      }
    }

    if (!uid) {
      throw new Error("Could not resolve a valid numeric User ID (UID) from Bambu account details.");
    }
    console.log(`[Cloud Bridge] Resolved user UID: ${uid}`);

    // 3. Fetch pre-sliced G-code package from static URL
    stages.push("Downloading pre-sliced G-code");
    const filename = gcode3mfUrl.split("/").pop() || "piece.gcode.3mf";
    console.log(`[Cloud Bridge] Fetching G-code archive from: ${gcode3mfUrl}`);
    const fileRes = await fetch(gcode3mfUrl);
    if (!fileRes.ok) {
      throw new Error(`Failed to fetch G-code from static URL: HTTP ${fileRes.status}`);
    }

    const buffer = Buffer.from(await fileRes.arrayBuffer());
    const size = buffer.length;
    console.log(`[Cloud Bridge] Package downloaded: ${filename} (${(size / 1024).toFixed(1)} KB)`);

    // Calculate MD5 hash for the printing payload (if possible from zip, or just random hash / empty)
    // Bambu Cloud print command checks MD5 of plate_1.gcode or the 3mf package to ensure payload integrity
    const md5Hash = crypto.createHash("md5").update(buffer).digest("hex");

    // 4. Request pre-signed S3 upload slot from Bambu Cloud
    stages.push("Requesting Bambu AWS S3 slot");
    const uploadReqUrl = `https://api.bambulab.com/v1/iot-service/api/user/upload?filename=${encodeURIComponent(filename)}&size=${size}`;
    const uploadSlotRes = await fetch(uploadReqUrl, {
      headers: { "Authorization": `Bearer ${accessToken}` }
    });

    if (!uploadSlotRes.ok) {
      throw new Error(`Failed to fetch S3 presign slot: HTTP ${uploadSlotRes.status}`);
    }

    const uploadSlotData = await uploadSlotRes.json();
    const { url, size_url } = uploadSlotData;

    if (!url || !size_url) {
      throw new Error("Bambu Cloud did not provide valid pre-signed AWS upload URLs.");
    }

    // 5. Upload stream directly to Bambu Storage (AWS S3)
    stages.push("Streaming G-code to S3");
    console.log("[Cloud Bridge] Uploading raw package to primary AWS S3 slot...");
    const putFileRes = await fetch(url, {
      method: "PUT",
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Length": String(size)
      },
      body: buffer
    });

    if (!putFileRes.ok) {
      throw new Error(`Primary S3 upload failed with HTTP status ${putFileRes.status}`);
    }

    console.log("[Cloud Bridge] Uploading file size metadata to size S3 slot...");
    const putSizeRes = await fetch(size_url, {
      method: "PUT",
      headers: {
        "Content-Type": "text/plain",
        "Content-Length": String(String(size).length)
      },
      body: String(size)
    });

    if (!putSizeRes.ok) {
      throw new Error(`Metadata S3 size upload failed with HTTP status ${putSizeRes.status}`);
    }

    // 6. Connect to Bambu Cloud MQTT TLS Broker
    stages.push("Connecting to MQTT TLS Broker");
    const cleanDownloadUrl = url.split("?")[0];
    console.log(`[Cloud Bridge] File is live. Direct download URL: ${cleanDownloadUrl}`);

    const brokerUrl = "mqtts://us.mqtt.bambulab.com:8883";
    console.log(`[Cloud Bridge] Opening secure MQTT socket to ${brokerUrl}...`);

    const mqttClient = mqtt.connect(brokerUrl, {
      username: `u_${uid}`,
      password: accessToken,
      rejectUnauthorized: false // Bambu Cloud TLS brokers use internal/custom certs
    });

    mqttClient.on("connect", () => {
      stages.push("Publishing cloud print command");
      console.log("[Cloud Bridge] MQTT Connected! Sending project_file command...");

      const topic = `device/${serialNumber}/request`;
      const payload = {
        print: {
          sequence_id: String(Math.floor(Date.now() / 1000)),
          command: "project_file",
          url: cleanDownloadUrl,
          param: "Metadata/plate_1.gcode",
          project_id: "0",
          profile_id: "0",
          task_id: "0",
          subtask_id: "0",
          subtask_name: filename.replace(".gcode.3mf", ""),
          file: filename,
          use_ams: false,
          timelapse: false,
          bed_type: "auto",
          auto_bed_leveling: 1,
          flow_cali: false,
          bed_leveling: true,
          vibration_cali: false,
          layer_inspect: false,
          ams_mapping: [],
          cfg: "0",
          md5: md5Hash
        }
      };

      mqttClient.publish(topic, JSON.stringify(payload, null, 0), { qos: 1 }, (err) => {
        if (err) {
          console.error("[Cloud Bridge] MQTT publish error:", err);
          mqttClient.end();
          return res.status(502).json({
            ok: false,
            message: `MQTT print publish failed: ${err.message}`,
            stages
          });
        }
        
        console.log("[Cloud Bridge] MQTT command sent successfully!");
        mqttClient.end();

        stages.push("Print triggered successfully!");
        return res.json({
          ok: true,
          message: "Print command dispatched via cloud MQTT broker successfully.",
          filename,
          downloadUrl: cleanDownloadUrl,
          stages
        });
      });
    });

    mqttClient.on("error", (err) => {
      console.error("[Cloud Bridge] MQTT connection error:", err);
      mqttClient.end();
      return res.status(502).json({
        ok: false,
        message: `MQTT Broker connection failed: ${err.message}`,
        stages
      });
    });

  } catch (error) {
    console.error("[Cloud Bridge] Operation error:", error.message);
    return res.status(500).json({
      ok: false,
      message: error.message,
      stages
    });
  }
});

// Health check endpoint
app.get("/health", (req, res) => {
  res.json({ ok: true, version: "1.0.0", mode: "Cloud-to-Cloud" });
});

app.listen(PORT, () => {
  console.log(`[Enigma Cloud Bridge] Running on port ${PORT}`);
  console.log(`[Enigma Cloud Bridge] Mode: Alternative A (Cloud-to-Cloud Slicerless)`);
});
