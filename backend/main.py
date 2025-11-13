from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from io import BytesIO
import base64
import json
import os
from dotenv import load_dotenv
import logging
import re
import pandas as pd
from openai import OpenAI
from pathlib import Path

# --------------------------------------------------------------------------- #
# Logging & OpenAI init
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY environment variable not set")
    raise RuntimeError("OPENAI_API_KEY environment variable not set")

try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise RuntimeError(f"Failed to initialize OpenAI client: {e}")

# --------------------------------------------------------------------------- #
# FastAPI app
# --------------------------------------------------------------------------- #
app = FastAPI(title="Insurance Policy Processing System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://zuno-image-report.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Formula data (only Digit) - FIXED VERSION
# --------------------------------------------------------------------------- #
FORMULA_DATA = [
    {"LOB": "TW", "SEGMENT": "1+5", "PO": "90% of Payin", "REMARKS": "NIL"},
    {"LOB": "TW", "SEGMENT": "TW SAOD + COMP", "PO": "90% of Payin", "REMARKS": "NIL"},
    {"LOB": "TW", "SEGMENT": "TW TP", "PO": "-2%", "REMARKS": "Payin Below 20%"},
    {"LOB": "TW", "SEGMENT": "TW TP", "PO": "-3%", "REMARKS": "Payin 21% to 30%"},
    {"LOB": "TW", "SEGMENT": "TW TP", "PO": "-4%", "REMARKS": "Payin 31% to 50%"},
    {"LOB": "TW", "SEGMENT": "TW TP", "PO": "-5%", "REMARKS": "Payin Above 50%"},
    {"LOB": "PVT CAR", "SEGMENT": "PVT CAR COMP + SAOD", "PO": "90% of Payin", "REMARKS": "NIL"},
    # CRITICAL FIX: Added default NIL rule for PVT CAR TP
    {"LOB": "PVT CAR", "SEGMENT": "PVT CAR TP", "PO": "21", "REMARKS": "NIL"},
    {"LOB": "PVT CAR", "SEGMENT": "PVT CAR TP", "PO": "21", "REMARKS": "Zuno - 21"},
    {"LOB": "CV", "SEGMENT": "All GVW & PCV 3W, GCV 3W", "PO": "-2%", "REMARKS": "Payin Below 20%"},
    {"LOB": "CV", "SEGMENT": "All GVW & PCV 3W, GCV 3W", "PO": "-3%", "REMARKS": "Payin 21% to 30%"},
    {"LOB": "CV", "SEGMENT": "All GVW & PCV 3W, GCV 3W", "PO": "-4%", "REMARKS": "Payin 31% to 50%"},
    {"LOB": "CV", "SEGMENT": "All GVW & PCV 3W, GCV 3W", "PO": "-5%", "REMARKS": "Payin Above 50%"},
    {"LOB": "BUS", "SEGMENT": "SCHOOL BUS", "PO": "88% of Payin", "REMARKS": "NIL"},
    {"LOB": "BUS", "SEGMENT": "STAFF BUS", "PO": "88% of Payin", "REMARKS": "NIL"},
    {"LOB": "TAXI", "SEGMENT": "TAXI", "PO": "-2%", "REMARKS": "Payin Below 20%"},
    {"LOB": "TAXI", "SEGMENT": "TAXI", "PO": "-3%", "REMARKS": "Payin 21% to 30%"},
    {"LOB": "TAXI", "SEGMENT": "TAXI", "PO": "-4%", "REMARKS": "Payin 31% to 50%"},
    {"LOB": "TAXI", "SEGMENT": "TAXI", "PO": "-5%", "REMARKS": "Payin Above 50%"},
    {"LOB": "MISD", "SEGMENT": "Misd, Tractor", "PO": "88% of Payin", "REMARKS": "NIL"},
]

# --------------------------------------------------------------------------- #
# OCR extraction
# --------------------------------------------------------------------------- #
def extract_text_from_file(file_bytes: bytes, filename: str, content_type: str) -> str:
    file_ext = filename.split(".")[-1].lower() if "." in filename else ""
    if file_ext not in {"png", "jpg", "jpeg", "gif", "bmp", "tiff"} and not content_type.startswith(
        "image/"
    ):
        raise ValueError(f"Unsupported file type: {filename}")

    try:
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        prompt = """
You are extracting insurance policy data from an image. Return a JSON array with these exact keys: segment, policy_type, location, payin, remark.

STEP-BY-STEP EXTRACTION:

STEP 1: Identify the vehicle/policy category
- 2W, MC, MCY, SC, Scooter, EV → TWO WHEELER
- PVT CAR, Car, PCI → PRIVATE CAR  
- CV, GVW, PCV, GCV, tonnage → COMMERCIAL VEHICLE
- Bus → BUS
- Taxi → TAXI
- Tractor, Ambulance, Misd → MISCELLANEOUS

STEP 2: Identify policy type from columns
- 1+1 column = Comp
- SATP column = TP
- If both exist, create TWO separate records

STEP 3: Map to EXACT segment (MANDATORY):

TWO WHEELER:
  IF 1+1 OR Comp OR SAOD → segment = "TW SAOD + COMP"
  IF SATP OR TP → segment = "TW TP"
  IF New/Fresh/1+5 → segment = "1+5"
  NEVER use "2W", "MC", "Scooter" as segment

PRIVATE CAR:
  IF 1+1 OR Comp OR SAOD → segment = "PVT CAR COMP + SAOD"
  IF SATP OR TP → segment = "PVT CAR TP"
  and 4W means 4 wheeler means Private Car 

COMMERCIAL VEHICLE:
  ALWAYS → segment = "All GVW & PCV 3W, GCV 3W"
  (Digit treats all CV the same regardless of tonnage)

BUS:
  IF School → segment = "SCHOOL BUS"
  ELSE → segment = "STAFF BUS"

TAXI:
  segment = "TAXI"

MISCELLANEOUS:
  segment = "Misd, Tractor"

STEP 4: Extract other fields
- policy_type: "Comp" or "TP"
- location: Cluster/Agency name
- payin: ONLY CD2 value as NUMBER (ignore CD1)
- remark: Additional details as STRING

CRITICAL RULES:
- payin must be numeric (63.0 not "63.0%")
- Create separate records if both 1+1 and SATP columns exist
- NEVER use raw names like "2W" in segment
- Handle negative % as positive


If this data is given :
PCVC Auto: Upto 2 years : 69%
above 2 years:70%
4W TP,2W COMP,4W COMP and Non Eb 2.5% VLI for year 25-26

then please consider 

PCV Auto  which is PCV 3w as Auto is 3W which is 69% bove 2 years , 70% and remark should be upto 2 years if parsed 69%
and above 2 years if parsed 70%
and a

I hope you 

also there is one more column , if CD2 or any other column is given then consider that column as payin value,
if it contains multiplestuff

for example : COMP and sub column : CD2 contains for example Tata 30%; any other makes : 28%/26%, then consider the lowest value please , so the output should contain for both , 30% and the remark Tata , and 26% , in the remark other make 

Also note: wherever you find out the Payrate , but if it lies in range of 0 to 100 % then please consider it 
For example , PO or can say payrate can contain these column and under it , it contains the value , so please confider this also if it contains values 

here is the table

State / Location,Seating Capacity,School Bus – In the name of school and Yellow Bus (Contract transporter),On Contract (Transporter),On Contract (Individual)
"All of India
excl Below locations",8 & above,75%,62.5%,62.5%
Rajasthan and Bengaluru,8 & above,70%,62.5%,62.5%
"Tamil Nadu, Kerala,
Rest of KA (KA excl Bengaluru),
Madhya Pradesh",8 & above,55%,52.5%,50%


The above table which I gave it to you was an example , so please consider the payrates wherever it is given , please do it so 
so please consider the 75% onwards also , please
and the other columns can be on contract (transporter) and on contract (individual)

Do one thing , please consider wherever you get the payrate ose sense the payrate which is in percentage

Return ONLY JSON array, no markdown.
"""
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{file_ext};base64,{image_b64}"},
                        },
                    ],
                }
            ],
            temperature=0,
            max_tokens=4000,
        )
        raw = response.choices[0].message.content.strip()
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()
        start = cleaned.find("[")
        end = cleaned.rfind("]") + 1
        if start != -1 and end > start:
            cleaned = cleaned[start:end]
        json.loads(cleaned)  # validate
        return cleaned
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return "[]"

# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
def classify_payin(payin_value):
    try:
        if isinstance(payin_value, (int, float)):
            v = float(payin_value)
        else:
            v = float(str(payin_value).replace("%", "").replace(" ", "").replace("-", "").strip())
        if v <= 20:
            return v, "Payin Below 20%"
        if v <= 30:
            return v, "Payin 21% to 30%"
        if v <= 50:
            return v, "Payin 31% to 50%"
        return v, "Payin Above 50%"
    except Exception:
        return 0.0, "Payin Below 20%"

def determine_lob(segment: str) -> str:
    s = segment.upper()
    if "BUS" in s:
        return "BUS"
    if any(k in s for k in ("TW", "2W", "MC", "SC", "1+5")):
        return "TW"
    if any(k in s for k in ("PVT CAR", "CAR", "PCI")):
        return "PVT CAR"
    if any(k in s for k in ("CV", "GVW", "PCV", "GCV")):
        return "CV"
    if "TAXI" in s:
        return "TAXI"
    if any(k in s for k in ("MISD", "TRACTOR")):
        return "MISD"
    return "UNKNOWN"

# --------------------------------------------------------------------------- #
# Core formula application - COMPLETELY REWRITTEN
# --------------------------------------------------------------------------- #
def apply_formula(policy_data):
    if not policy_data:
        return []

    result = []
    for rec in policy_data:
        try:
            segment = str(rec.get("segment", ""))
            payin_val = rec.get("Payin_Value", 0.0)
            payin_cat = rec.get("Payin_Category", "")
            
            # Get remark - handle both direct string and nested formats
            remark = rec.get("remark", "")
            if isinstance(remark, list):
                remark = " ".join(map(str, remark))
            remark = str(remark).strip()

            # ---------- ZUNO OVERRIDE (HIGHEST PRIORITY) ----------
            # Check for Zuno - 21 pattern (case insensitive, flexible spacing)
            zuno_pattern = r"Zuno\s*[-–—]\s*21"
            if re.search(zuno_pattern, remark, re.IGNORECASE):
                payout = 21.0
                formula = "Zuno - 21 (from remark)"
                explanation = "Remark contains 'Zuno - 21' → Fixed payout of 21%"
                
                result.append({
                    "segment": segment,
                    "policy type": rec.get("policy_type", "Comp"),
                    "location": rec.get("location", "N/A"),
                    "payin": f"{payin_val:.2f}%",
                    "remark": remark,
                    "Calculated Payout": f"{payout:.2f}%",
                    "Formula Used": formula,
                    "Rule Explanation": explanation,
                })
                continue  # Skip normal rule processing

            # ---------- NORMAL RULE MATCH ----------
            lob = determine_lob(segment)
            seg_up = segment.upper()
            matched = None
            
            # Try to find matching rule
            # First pass: Look for specific payin category matches or Zuno matches
            for rule in FORMULA_DATA:
                if rule["LOB"] != lob:
                    continue
                if rule["SEGMENT"].upper() not in seg_up:
                    continue
                    
                rmrk = rule.get("REMARKS", "").strip()
                
                # Check for specific matches first
                if rmrk != "NIL" and (payin_cat in rmrk or rmrk in remark):
                    matched = rule
                    break
            
            # Second pass: If no specific match found, look for NIL rules
            if not matched:
                for rule in FORMULA_DATA:
                    if rule["LOB"] != lob:
                        continue
                    if rule["SEGMENT"].upper() not in seg_up:
                        continue
                    
                    rmrk = rule.get("REMARKS", "").strip()
                    if rmrk == "NIL":
                        matched = rule
                        break

            if matched:
                po = matched["PO"]
                payout = payin_val

                # Apply the formula
                if po == "21":
                    payout = 21.0
                elif "90% of Payin" in po:
                    payout *= 0.9
                elif "88% of Payin" in po:
                    payout *= 0.88
                elif "Less 2%" in po or "-2%" in po:
                    payout -= 2
                elif "-3%" in po:
                    payout -= 3
                elif "-4%" in po:
                    payout -= 4
                elif "-5%" in po:
                    payout -= 5

                payout = max(0.0, payout)
                formula = po
                explanation = f"LOB={lob}, Segment={matched['SEGMENT']}, Rule={matched['REMARKS']}"
            else:
                payout = payin_val
                formula = "No matching rule"
                explanation = f"No rule for LOB={lob}, Segment={seg_up}, Payin={payin_cat}"

            # ---------- FORMAT OUTPUT ----------
            result.append({
                "segment": segment,
                "policy type": rec.get("policy_type", "Comp"),
                "location": rec.get("location", "N/A"),
                "payin": f"{payin_val:.2f}%",
                "remark": remark,
                "Calculated Payout": f"{payout:.2f}%",
                "Formula Used": formula,
                "Rule Explanation": explanation,
            })
            
        except Exception as e:
            logger.error(f"Error processing record {rec}: {e}")
            result.append({
                "segment": str(rec.get("segment", "Unknown")),
                "policy type": rec.get("policy_type", "Comp"),
                "location": rec.get("location", "N/A"),
                "payin": str(rec.get("payin", "0%")),
                "remark": str(rec.get("remark", "Error")),
                "Calculated Payout": "Error",
                "Formula Used": "Error",
                "Rule Explanation": f"Error: {e}",
            })
            
    return result

# --------------------------------------------------------------------------- #
# Main processing pipeline
# --------------------------------------------------------------------------- #
def process_files(policy_file_bytes: bytes, policy_filename: str, policy_content_type: str, company_name: str):
    logger.info(f"Processing {policy_filename} for {company_name}")

    extracted = extract_text_from_file(policy_file_bytes, policy_filename, policy_content_type)
    if not extracted or extracted == "[]":
        raise ValueError("No text extracted from image")

    data = json.loads(extracted)
    if isinstance(data, dict):
        data = [data]

    # classify pay-in
    for r in data:
        pv, pc = classify_payin(r.get("payin", 0))
        r["Payin_Value"] = pv
        r["Payin_Category"] = pc

    calculated = apply_formula(data)

    # Excel export
    df = pd.DataFrame(calculated)
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Policy Data", startrow=2, index=False)
        ws = writer.sheets["Policy Data"]
        for i, col in enumerate(df.columns, 1):
            ws.cell(row=3, column=i, value=col).font = ws.cell(row=3, column=i).font.copy(bold=True)
        title = ws.cell(row=1, column=1, value=f"{company_name} - Policy Data")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(df.columns))
        title.font = title.font.copy(bold=True, size=14)
        title.alignment = title.alignment.copy(horizontal="center")
    out.seek(0)
    excel_b64 = base64.b64encode(out.read()).decode("utf-8")

    # metrics
    avg_payin = sum(r["Payin_Value"] for r in data) / len(data)
    formula_sum = {}
    for r in calculated:
        formula_sum[r["Formula Used"]] = formula_sum.get(r["Formula Used"], 0) + 1

    return {
        "extracted_text": extracted,
        "parsed_data": data,
        "calculated_data": calculated,
        "excel_data": excel_b64,
        "csv_data": df.to_csv(index=False),
        "json_data": json.dumps(calculated, indent=2),
        "formula_data": FORMULA_DATA,
        "metrics": {
            "total_records": len(calculated),
            "avg_payin": round(avg_payin, 1),
            "unique_segments": len({r["segment"] for r in calculated}),
            "company_name": company_name,
            "formula_summary": formula_sum,
        },
    }

# --------------------------------------------------------------------------- #
# API routes
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def root():
    p = Path("index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Insurance Policy Processing System</h1><p>POST /process</p>")

@app.post("/process")
async def process_policy(company_name: str = Form(...), policy_file: UploadFile = File(...)):
    try:
        bytes_data = await policy_file.read()
        if not bytes_data:
            return JSONResponse(status_code=400, content={"error": "Empty file"})
        return JSONResponse(content=process_files(bytes_data, policy_file.filename, policy_file.content_type, company_name))
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"Processing failed: {e}"})

@app.get("/health")
async def health_check():
    return JSONResponse({"status": "healthy"})

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting server at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
