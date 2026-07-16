// ===========================================================================
// MagneticForce.cpp - Implementation File
// ===========================================================================

#include "MagneticForce.h"
#include "PluginConstants.h"
#include "Helpers.h"
#include <fstream>
#include <sstream>
#include <algorithm>
#include <iostream>
#include <limits>

// Constructor
CMagneticForce::CMagneticForce()
    : m_activationTime(10.0)
    , m_mu0(1.2566e-6)
    , m_chiPropertyName("Chi_P")
    , m_fieldFileName("B_output.txt")
    , m_nx(0)
    , m_ny(0)
    , m_xMin(0), m_xMax(0)
    , m_yMin(0), m_yMax(0)
    , m_dx(0), m_dy(0)
{
}

// Setup - called once at start
bool CMagneticForce::setup(
    NApiHelpers::CFlags<EApiExternalForceFeatureFlags>& featureFlags,
    NApiHelpers::CFlags<NApi::EApiSolverFlags>& solverFlags,
    NApiHelpers::CFlags<NApi::EApiParticleShapeFlags>& particleShapeFlags,
    NApiHelpers::CSimpleString& physicsModelName,
    const char prefFile[],
    char customMsg[NApi::ERROR_MSG_MAX_LENGTH])
{
    // Enable custom properties
    featureFlags.enableFlag(EApiExternalForceFeatureFlags::usesCustomProperties);
    featureFlags.enableFlag(EApiExternalForceFeatureFlags::pluginGUIEnabled);
    
    physicsModelName = "Magnetic Force Coupling";
    
    return true;
}

// Define GUI parameters
void CMagneticForce::setApiParametersTemplate() const
{
    auto* apiManager = getApiManager();
    auto* paramManager = apiManager->getParameterManager();
    
    paramManager->startGroup(NPluginParamsGroupNames::PARTICLE_BODY_FORCE);
        paramManager->addDoubleValue(10.0, "Activation Time", NApi::eTime);
        paramManager->addStringValue("B_output.txt", "Field Data File");
        paramManager->addStringValue("Chi_P", "Susceptibility Property Name");
    paramManager->endGroup();
}

// Starting - called once after setup
bool CMagneticForce::starting(
    int numThreads,
    char guiPath[NApi::GUI_FILE_MAX_LENGTH])
{
    std::cout << "\n======================================================================\n";
    std::cout << "INITIALIZING MAGNETIC FORCE COUPLING\n";
    std::cout << "======================================================================\n";
    
    // Get parameters from GUI
    auto* apiManager = getApiManager();
    auto* paramManager = apiManager->getParameterManager();
    
    paramManager->openGroup(NPluginParamsGroupNames::PARTICLE_BODY_FORCE);
        m_activationTime = paramManager->getDoubleValue("Activation Time");
        m_fieldFileName = paramManager->getStringValue("Field Data File");
        m_chiPropertyName = paramManager->getStringValue("Susceptibility Property Name");
    paramManager->endGroup();
    
    std::cout << "  Activation time: " << m_activationTime << " s\n";
    std::cout << "  Field file: " << m_fieldFileName << "\n";
    std::cout << "  Chi property: " << m_chiPropertyName << "\n";
    
    // Register custom property
    auto* propManager = apiManager->getCustomPropertyManager();
    if (propManager->isPropertyAvailable(NApi::eParticle, m_chiPropertyName.c_str())) {
        std::cout << "  Custom property '" << m_chiPropertyName << "' found\n";
    } else {
        std::cout << "  WARNING: Custom property '" << m_chiPropertyName << "' not found!\n";
        std::cout << "  Please create this property in EDEM Creator.\n";
    }
    
    // Load field data
    if (!loadFieldData(m_fieldFileName.c_str())) {
        std::cout << "  ERROR: Failed to load field data!\n";
        return false;
    }
    
    std::cout << "======================================================================\n";
    std::cout << "MAGNETIC FORCE COUPLING INITIALIZED SUCCESSFULLY\n";
    std::cout << "======================================================================\n\n";
    
    return true;
}

// Load and process FEMM field data
bool CMagneticForce::loadFieldData(const char* filename)
{
    std::cout << "\n--- Loading Field Data ---\n";
    
    std::ifstream file(filename);
    if (!file.is_open()) {
        std::cout << "  ERROR: Cannot open file: " << filename << "\n";
        return false;
    }
    
    m_fieldData.clear();
    std::string line;
    int lineNum = 0;
    
    // Skip header lines starting with #
    while (std::getline(file, line)) {
        lineNum++;
        if (line.empty() || line[0] == '#') continue;
        break;
    }
    
    // Parse data lines
    do {
        if (line.empty() || line[0] == '#') continue;
        
        std::istringstream iss(line);
        FieldPoint pt;
        double x_cm, y_cm;
        double B_mag, dBmag_dx, dBmag_dy, A, Energy;
        int region;
        double dBx_dx, dBx_dy, dBy_dx, dBy_dy;
        
        // Parse: X Y Bx By B_mag dBx_dx dBx_dy dBy_dx dBy_dy ...
        if (!(iss >> x_cm >> y_cm >> pt.Bx >> pt.By >> B_mag 
              >> dBx_dx >> dBx_dy >> dBy_dx >> dBy_dy)) {
            continue; // Skip malformed lines
        }
        
        // Convert units: cm -> m, T/cm -> T/m
        pt.x = x_cm / 100.0;
        pt.y = y_cm / 100.0;
        
        // Calculate (B·∇)B force gradients [T²/m]
        pt.gradBx = pt.Bx * (dBx_dx * 100.0) + pt.By * (dBx_dy * 100.0);
        pt.gradBy = pt.Bx * (dBy_dx * 100.0) + pt.By * (dBy_dy * 100.0);
        
        m_fieldData.push_back(pt);
        
    } while (std::getline(file, line));
    
    file.close();
    
    std::cout << "  Loaded " << m_fieldData.size() << " field points\n";
    
    if (m_fieldData.empty()) {
        std::cout << "  ERROR: No valid data found!\n";
        return false;
    }
    
    // Identify unique grid coordinates
    std::vector<double> allX, allY;
    for (const auto& pt : m_fieldData) {
        allX.push_back(pt.x);
        allY.push_back(pt.y);
    }
    
    std::sort(allX.begin(), allX.end());
    std::sort(allY.begin(), allY.end());
    allX.erase(std::unique(allX.begin(), allX.end()), allX.end());
    allY.erase(std::unique(allY.begin(), allY.end()), allY.end());
    
    m_xGrid = allX;
    m_yGrid = allY;
    m_nx = m_xGrid.size();
    m_ny = m_yGrid.size();
    
    m_xMin = m_xGrid.front();
    m_xMax = m_xGrid.back();
    m_yMin = m_yGrid.front();
    m_yMax = m_yGrid.back();
    
    if (m_nx > 1) m_dx = (m_xMax - m_xMin) / (m_nx - 1);
    if (m_ny > 1) m_dy = (m_yMax - m_yMin) / (m_ny - 1);
    
    std::cout << "  Grid: " << m_nx << " x " << m_ny << " points\n";
    std::cout << "  X range: [" << m_xMin << ", " << m_xMax << "] m\n";
    std::cout << "  Y range: [" << m_yMin << ", " << m_yMax << "] m\n";
    std::cout << "  Domain: " << (m_xMax-m_xMin)*100 << " x " 
              << (m_yMax-m_yMin)*100 << " cm\n";
    
    // Crop to coil region
    cropFieldToCoilRegion();
    
    return true;
}

// Crop field data to magnetic coil region
void CMagneticForce::cropFieldToCoilRegion()
{
    std::cout << "\n--- Cropping to Coil Region ---\n";
    
    // Find max gradient magnitude
    double maxGrad = 0.0;
    for (const auto& pt : m_fieldData) {
        double gradMag = std::sqrt(pt.gradBx * pt.gradBx + pt.gradBy * pt.gradBy);
        if (gradMag > maxGrad) maxGrad = gradMag;
    }
    
    std::cout << "  Max gradient: " << maxGrad << " T²/m\n";
    
    // Define threshold (5% of max)
    double threshold = 0.05 * maxGrad;
    std::cout << "  Threshold (5%): " << threshold << " T²/m\n";
    
    // Find bounding box of high-gradient region
    double xMinCoil = std::numeric_limits<double>::max();
    double xMaxCoil = std::numeric_limits<double>::lowest();
    double yMinCoil = std::numeric_limits<double>::max();
    double yMaxCoil = std::numeric_limits<double>::lowest();
    
    for (const auto& pt : m_fieldData) {
        double gradMag = std::sqrt(pt.gradBx * pt.gradBx + pt.gradBy * pt.gradBy);
        if (gradMag > threshold) {
            if (pt.x < xMinCoil) xMinCoil = pt.x;
            if (pt.x > xMaxCoil) xMaxCoil = pt.x;
            if (pt.y < yMinCoil) yMinCoil = pt.y;
            if (pt.y > yMaxCoil) yMaxCoil = pt.y;
        }
    }
    
    // Add 5% margin
    double xMargin = 0.05 * (xMaxCoil - xMinCoil);
    double yMargin = 0.05 * (yMaxCoil - yMinCoil);
    xMinCoil -= xMargin;
    xMaxCoil += xMargin;
    yMinCoil -= yMargin;
    yMaxCoil += yMargin;
    
    std::cout << "  Original: X=[" << m_xMin << ", " << m_xMax << "], "
              << "Y=[" << m_yMin << ", " << m_yMax << "] m\n";
    std::cout << "  Cropped:  X=[" << xMinCoil << ", " << xMaxCoil << "], "
              << "Y=[" << yMinCoil << ", " << yMaxCoil << "] m\n";
    
    // Update bounds
    m_xMin = xMinCoil;
    m_xMax = xMaxCoil;
    m_yMin = yMinCoil;
    m_yMax = yMaxCoil;
    
    std::cout << "  Coil size: " << (m_xMax-m_xMin)*100 << " x " 
              << (m_yMax-m_yMin)*100 << " cm\n";
}

// Bilinear interpolation of force gradients
bool CMagneticForce::interpolateForce(double x, double y, double& gradBx, double& gradBy)
{
    // Check if point is within field domain
    if (x < m_xMin || x > m_xMax || y < m_yMin || y > m_yMax) {
        gradBx = 0.0;
        gradBy = 0.0;
        return false;
    }
    
    // Find grid cell
    int ix = static_cast<int>((x - m_xMin) / m_dx);
    int iy = static_cast<int>((y - m_yMin) / m_dy);
    
    // Clamp to valid range
    if (ix < 0) ix = 0;
    if (ix >= m_nx - 1) ix = m_nx - 2;
    if (iy < 0) iy = 0;
    if (iy >= m_ny - 1) iy = m_ny - 2;
    
    // Get corner points
    double x0 = m_xGrid[ix];
    double x1 = m_xGrid[ix + 1];
    double y0 = m_yGrid[iy];
    double y1 = m_yGrid[iy + 1];
    
    // Normalized coordinates
    double tx = (x - x0) / (x1 - x0);
    double ty = (y - y0) / (y1 - y0);
    
    // Find data at corners (simple lookup)
    // Note: This assumes regular grid structure
    int idx00 = iy * m_nx + ix;
    int idx10 = iy * m_nx + (ix + 1);
    int idx01 = (iy + 1) * m_nx + ix;
    int idx11 = (iy + 1) * m_nx + (ix + 1);
    
    if (idx11 >= m_fieldData.size()) {
        gradBx = 0.0;
        gradBy = 0.0;
        return false;
    }
    
    // Bilinear interpolation
    double gx00 = m_fieldData[idx00].gradBx;
    double gx10 = m_fieldData[idx10].gradBx;
    double gx01 = m_fieldData[idx01].gradBx;
    double gx11 = m_fieldData[idx11].gradBx;
    
    double gy00 = m_fieldData[idx00].gradBy;
    double gy10 = m_fieldData[idx10].gradBy;
    double gy01 = m_fieldData[idx01].gradBy;
    double gy11 = m_fieldData[idx11].gradBy;
    
    gradBx = (1-tx) * (1-ty) * gx00 + tx * (1-ty) * gx10
           + (1-tx) * ty * gx01 + tx * ty * gx11;
    
    gradBy = (1-tx) * (1-ty) * gy00 + tx * (1-ty) * gy10
           + (1-tx) * ty * gy01 + tx * ty * gy11;
    
    return true;
}

// Calculate external force - called for each particle each timestep
ECalculateResult CMagneticForce::externalForce(
    int threadID,
    const NExternalForceTypes::STimeStepData& timeStepData,
    const NExternalForceTypes::SParticle& particle,
    NApiCore::ICustomPropertyDataApi_1_0* particleCustomProperties,
    NApiCore::ICustomPropertyDataApi_1_0* simulationCustomProperties,
    NExternalForceTypes::SResults& results)
{
    // Check if magnetic force should be active
    if (timeStepData.m_time < m_activationTime) {
        results.m_force[0] = 0.0;
        results.m_force[1] = 0.0;
        results.m_force[2] = 0.0;
        return eSuccess;
    }
    
    // Get particle susceptibility
    double chiP = 0.0;
    if (particleCustomProperties != nullptr) {
        double* chiData = particleCustomProperties->getValueForReadAndWrite(
            m_chiPropertyName.c_str());
        if (chiData != nullptr) {
            chiP = chiData[0];
        }
    }
    
    // Skip non-magnetic particles
    if (std::abs(chiP) < 1e-10) {
        results.m_force[0] = 0.0;
        results.m_force[1] = 0.0;
        results.m_force[2] = 0.0;
        return eSuccess;
    }
    
    // Get particle position and volume
    double x = particle.m_position[0]; // [m]
    double y = particle.m_position[1]; // [m]
    double volume = particle.m_volume;  // [m³]
    
    // Interpolate force gradients at particle position
    double gradBx, gradBy;
    if (!interpolateForce(x, y, gradBx, gradBy)) {
        // Outside field domain
        results.m_force[0] = 0.0;
        results.m_force[1] = 0.0;
        results.m_force[2] = 0.0;
        return eSuccess;
    }
    
    // Calculate magnetic force: F = (V * chi_p / mu_0) * grad(0.5*B²)
    double forceScale = (volume * chiP) / m_mu0;
    
    results.m_force[0] = forceScale * gradBx; // [N]
    results.m_force[1] = forceScale * gradBy; // [N]
    results.m_force[2] = 0.0; // 2D planar field
    
    return eSuccess;
}

// Stopping - cleanup
bool CMagneticForce::stopping()
{
    m_fieldData.clear();
    m_xGrid.clear();
    m_yGrid.clear();
    return true;
}