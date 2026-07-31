# =============================================================================
# WSL2 Setup Commands for Windows (Run as Administrator)
# =============================================================================
# Save this file and run in PowerShell as Administrator
# Or copy-paste each command section one at a time
# =============================================================================

# -----------------------------------------------------------------------------
# STEP 1: Enable WSL2 and Virtual Machine Platform
# -----------------------------------------------------------------------------
# Run these commands in PowerShell as Administrator

dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

# After running above, RESTART your computer, then continue with Step 2

# -----------------------------------------------------------------------------
# STEP 2: Set WSL default version to 2 and install Ubuntu
# -----------------------------------------------------------------------------
# Run after restart

wsl --set-default-version 2
wsl --install -d Ubuntu-22.04

# Follow the prompts to create a username and password for Ubuntu
# After installation completes, Ubuntu terminal will open automatically

# -----------------------------------------------------------------------------
# STEP 3: Verify NVIDIA GPU access in WSL
# -----------------------------------------------------------------------------
# NVIDIA drivers for WSL are included in Windows NVIDIA drivers (version 470.76+)
# Download latest driver from: https://www.nvidia.com/Download/index.aspx
# 
# After installing Windows NVIDIA driver, run this in WSL Ubuntu terminal:
#   nvidia-smi
#
# You should see your RTX 3070 listed

# -----------------------------------------------------------------------------
# STEP 4: Run WSL setup script
# -----------------------------------------------------------------------------
# Open Ubuntu terminal (from Start menu or run: wsl -d Ubuntu-22.04)
# Then run:
#   bash /mnt/c/Users/ushni/Documents/SYNTH\ VEDA/scripts/wsl_setup.sh

# -----------------------------------------------------------------------------
# STEP 5: Run training
# -----------------------------------------------------------------------------
# In Ubuntu terminal:
#   bash /mnt/c/Users/ushni/Documents/SYNTH\ VEDA/scripts/wsl_train_nt.sh

# -----------------------------------------------------------------------------
# STEP 6: Run inference test
# -----------------------------------------------------------------------------
# In Ubuntu terminal:
#   bash /mnt/c/Users/ushni/Documents/SYNTH\ VEDA/scripts/wsl_infer_nt.sh

# =============================================================================
# QUICK REFERENCE - Copy-paste commands
# =============================================================================

# PowerShell (Admin) - Enable WSL2:
# dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart; dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

# PowerShell (after restart) - Install Ubuntu:
# wsl --set-default-version 2; wsl --install -d Ubuntu-22.04

# Ubuntu WSL - Run setup:
# bash /mnt/c/Users/ushni/Documents/SYNTH\ VEDA/scripts/wsl_setup.sh

# Ubuntu WSL - Run training:
# bash /mnt/c/Users/ushni/Documents/SYNTH\ VEDA/scripts/wsl_train_nt.sh

# Ubuntu WSL - Run inference:
# bash /mnt/c/Users/ushni/Documents/SYNTH\ VEDA/scripts/wsl_infer_nt.sh
