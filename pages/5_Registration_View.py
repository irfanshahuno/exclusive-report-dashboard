#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S3 Debug Script for Registration View
"""

import boto3
import streamlit as st
import pandas as pd
import io

# Use the same configuration
config = {
    "AWS_ACCESS_KEY_ID": "AWs-2ZGGXHTX4",
    "AWS_SECRET_ACCESS_KEY": "keyv7e7ez/dq1YJswx1V0A8b5tS1r",
    "AWS_REGION": "eu-north-1",
    "S3_BUCKET_NAME": "emc-rcm-storage-2026",
    "S3_BASE_PREFIX": "",
}

st.set_page_config(page_title="S3 Debug Tool", layout="wide")
st.title("🔍 S3 Debug Tool for Registration View")

# Initialize S3 client
try:
    s3 = boto3.client(
        "s3",
        region_name=config["AWS_REGION"],
        aws_access_key_id=config["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=config["AWS_SECRET_ACCESS_KEY"],
    )
    st.success("✅ S3 Connection Successful")
except Exception as e:
    st.error(f"❌ S3 Connection Failed: {e}")
    st.stop()

# List all objects with registration_summary prefix
st.header("1. Check Bucket Structure")
prefix = "registration_summary/"
try:
    response = s3.list_objects_v2(Bucket=config["S3_BUCKET_NAME"], Prefix=prefix)
    
    if 'Contents' not in response:
        st.error(f"No objects found with prefix: {prefix}")
        st.info("This means the upload page hasn't saved any data yet.")
    else:
        st.success(f"Found {len(response['Contents'])} objects")
        
        # Group by center
        centers = {}
        for obj in response['Contents']:
            path_parts = obj['Key'].split('/')
            if len(path_parts) > 1:
                center = path_parts[1] if len(path_parts) > 1 else "root"
                if center not in centers:
                    centers[center] = []
                centers[center].append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified']
                })
        
        # Display by center
        for center, objects in centers.items():
            with st.expander(f"📁 Center: {center} ({len(objects)} objects)", expanded=True):
                for obj in objects:
                    st.write(f"**Path:** `{obj['key']}`")
                    st.write(f"Size: {obj['size']} bytes | Modified: {obj['last_modified']}")
                    
                    # Try to read and display content
                    if obj['key'].endswith('.csv'):
                        try:
                            csv_obj = s3.get_object(Bucket=config["S3_BUCKET_NAME"], Key=obj['key'])
                            df = pd.read_csv(io.BytesIO(csv_obj['Body'].read()))
                            st.dataframe(df.head(), use_container_width=True)
                        except Exception as e:
                            st.error(f"Error reading CSV: {e}")
                    
                    elif obj['key'].endswith('.pkl'):
                        st.info("Pickle file - Use download button to inspect")
                        st.download_button(
                            label="Download pickle",
                            data=s3.get_object(Bucket=config["S3_BUCKET_NAME"], Key=obj['key'])['Body'].read(),
                            file_name=obj['key'].split('/')[-1],
                            mime="application/octet-stream"
                        )
                    
                    st.divider()
        
except Exception as e:
    st.error(f"Error listing objects: {e}")

# Test specific path construction
st.header("2. Test Path Construction")
st.write("Your centers are defined as:")
st.code("""
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}
""")

center_to_test = st.selectbox("Select center to test", 
                              ["easyhealth", "excellent", "pharmacy"])

# Construct paths as per your code
def s3_key(*parts: str) -> str:
    return "/".join([p.strip("/").strip() for p in parts if p is not None and str(p).strip() != ""])

def history_paths(center: str, base_prefix: str = ""):
    root = s3_key(base_prefix, "registration_summary", center)
    return root, s3_key(root, "history.csv")

root, hist_key = history_paths(center_to_test, config.get('S3_BASE_PREFIX',''))

st.write(f"**Root path:** `{root}`")
st.write(f"**History key:** `{hist_key}`")

# Check if history.csv exists
try:
    hist_obj = s3.get_object(Bucket=config["S3_BUCKET_NAME"], Key=hist_key)
    st.success(f"✅ history.csv exists at: {hist_key}")
    
    # Read and display history
    hist_df = pd.read_csv(io.BytesIO(hist_obj['Body'].read()))
    st.subheader("History DataFrame")
    st.dataframe(hist_df, use_container_width=True)
    
    # Check for latest day summary
    if not hist_df.empty and 'day' in hist_df.columns:
        latest_day = pd.to_datetime(hist_df['day'].max()).date()
        st.write(f"**Latest day in history:** {latest_day}")
        
        # Construct summary.pkl path
        summary_key = s3_key(root, str(latest_day), "summary.pkl")
        st.write(f"**Expected summary.pkl path:** `{summary_key}`")
        
        # Try to load it
        try:
            summary_obj = s3.get_object(Bucket=config["S3_BUCKET_NAME"], Key=summary_key)
            st.success(f"✅ summary.pkl exists at: {summary_key}")
            
            # Try to load pickle
            import pickle
            summary_data = pickle.loads(summary_obj['Body'].read())
            st.success("✅ Pickle loaded successfully!")
            st.write(f"**Keys in pickle:** {list(summary_data.keys())}")
            
            # Show sample of each dataframe
            for key, df in summary_data.items():
                with st.expander(f"DataFrame: {key}"):
                    if isinstance(df, pd.DataFrame):
                        st.write(f"Shape: {df.shape}")
                        st.dataframe(df.head(), use_container_width=True)
                    else:
                        st.write(f"Type: {type(df)}")
                        st.write(f"Value: {df}")
                        
        except s3.exceptions.NoSuchKey:
            st.error(f"❌ summary.pkl NOT found at: {summary_key}")
            st.info("Check if the upload page is saving summary.pkl correctly")
        except Exception as e:
            st.error(f"❌ Error loading pickle: {e}")
    
except s3.exceptions.NoSuchKey:
    st.error(f"❌ history.csv NOT found at: {hist_key}")
    st.info("The upload page needs to save history.csv first")
except Exception as e:
    st.error(f"❌ Error reading history.csv: {e}")

# Test bucket permissions
st.header("3. Test Permissions")
if st.button("Test Read/Write Permissions"):
    try:
        # Test write
        test_key = "test_permissions.txt"
        s3.put_object(
            Bucket=config["S3_BUCKET_NAME"],
            Key=test_key,
            Body=b"Test file for permissions check"
        )
        st.success("✅ Write permission: OK")
        
        # Test read
        obj = s3.get_object(Bucket=config["S3_BUCKET_NAME"], Key=test_key)
        st.success("✅ Read permission: OK")
        
        # Clean up
        s3.delete_object(Bucket=config["S3_BUCKET_NAME"], Key=test_key)
        st.success("✅ Delete permission: OK")
        
    except Exception as e:
        st.error(f"❌ Permission error: {e}")

st.header("4. Quick Fixes to Try")
st.markdown("""
1. **Check upload page is saving correctly:**
   - Open `4_Registration_Summary.py`
   - Make sure it's using the same S3 credentials
   - Check the save functions are being called

2. **Manual upload test:**
   ```python
   # In 4_Registration_Summary.py, add debug output:
   st.info(f"Saving to: {s3_key}")
