#ifndef HELPERSV3_8_0_H
#define HELPERSV3_8_0_H

/***************************************************************************/
/* This header file contains the V3.8.0 API helper functions and classes,  */
/* which are used to speed up calculations. Include this header into your  */
/* contact model project. These functions and methods will only change     */
/* when version changes.                                                   */
/* All functions and declarations are contained purely within this header. */
/***************************************************************************/

#include "IApiManager_1_1.h"
#include "HelpersV3_4_0.h"

namespace NApiHelpersV3_8_0
{
    namespace NApiHelpers = NApiHelpersV3_4_0;

    /***************************************************************************/
    /* Constant definitions of use in calculations                             */
    /***************************************************************************/
    const double SQRT5OVER6 = NApiHelpers::SQRT5OVER6;
    const double PI = NApiHelpers::PI;
    const double SMALL_NUMBER = NApiHelpers::SMALL_NUMBER;
    const double EQUAL_ZERO_CHECK_NUMBER = NApiHelpers::EQUAL_ZERO_CHECK_NUMBER;
    const double DOUBLE_UNDERFLOW = NApiHelpers::DOUBLE_UNDERFLOW;
    const double REALLY_REALLY_ZERO = NApiHelpers::REALLY_REALLY_ZERO;

    /***************************************************************************/
    /* Helper functions for double comparison                                  */
    /***************************************************************************/

    /**
     * Checks if a double is zero.  As doubles produce small variations
     * due to rounding this method returns true if
     * -DOUBLE_UNDERFLOW < val < DOUBLE_UNDERFLOW
     * @param val The value to check
     * @return bool True if the value is zero (within the tolerance)
     */
    using NApiHelpers::isZero;

    /**
     * Checks if a double is zero.  As doubles produce small variations
     * due to rounding this method returns true if
     * -tolerance < val < tolerance
     * The tolerance defaults to REALLY_REALLY_ZERO which is substantially more
     * limiting than the value used by isZero()
     * @param val The value to check
     * @param tolerance The tolerance to check to
     * @return bool True if the value is zero (within the tolerance)
     */
    using NApiHelpers::isReallyReallyZero;

    /**
     * Compares 2 doubles.  As doubles produce small variations due to
     * rounding this method allows the difference to be up to
     * REALLY_REALLY_ZERO (or another user supplied value)
     * @param valA The first value to check
     * @param valB The second value to check
     * @param zeroTol The tolerance to use in the zero check. A reasonable default is used if none is specified.
     * @param relTol The epsilon to use in the relative equality check. A reasonable default is used if none is specified.
     * @return bool True if the values are the same (within the tolerance)
     */
    using NApiHelpers::areEqual;

    /**
     * Tests 2 floating point values valA and valB for approximately equality or if valA is less than valB.
     * @param valA The first value to check
     * @param valB The second value to check
     * @param zeroTol The tolerance to use in the zero check. A reasonable default is used if none is specified.
     * @param relTol The epsilon to use in the relative equality check. A reasonable default is used if none is specified.
     * @return bool True if valA < valB or if valA and valB are approximately the same (based on the tolerances.)
     */
    using NApiHelpers::lessEqual;

    /**
     * Tests 2 floating point values valA and b for approximate equality or if valA is greater than valB.
     * @param valA The first value to check
     * @param valB The second value to check
     * @param zeroTol The tolerance to use in the zero check. A reasonable default is used if none is specified.
     * @param relTol The epsilon to use in the relative equality check. A reasonable default is used if none is specified.
     * @return bool True if valA > valB or if a and valB are approximately the same (based on the tolerances.)
     */
    using NApiHelpers::greaterEqual;

    /****************************************************************************/
    /* Class definitions for representation of matrices and vectors in 3D space */
    /****************************************************************************/

    /**
     * The CSimple3DVector class represents a vector in 3D space.
     */
    using NApiHelpers::CSimple3DVector;

    /**
     * The CSimple3x3Matrix class represents a 3x3 matrix.
     * Various operations to access and manipulate the matrix are provided
     */
    using NApiHelpers::CSimple3x3Matrix;

    /**
     * The CQuaternion class represents a quaternion.
     * Various operations to access and manipulate the quaternion are provided
     */
    using NApiHelpers::CQuaternion;

    /** helper operator */
    inline std::istream& operator>>(std::istream& stream, CSimple3DVector& vector)
    {
        stream >> vector.x >> vector.y >> vector.z;
    
        return stream;
    }

    /** When retrieving triangle nodes, vertex ids will be specified per triangle */
    using NApiHelpers::SGeomTriangleNode;

    /** wrapper for returning to EDEM strings from the API */
    using NApiHelpers::CSimpleString;

    /**
     * Pre-simulation flags that determine if certain values should be calculated
     * User set so we can avoid wasted cycles if they don't need calculated
     */
    template<typename enumType>
    class CFlags
    {
    public:
        /**
         * Enable a specific flag
         * @param feature The enum value of the feature that should be enabled
         */
        void enableFlag(enumType feature)
        {
            flags |= 1U << static_cast<unsigned int>(feature);
        }

        bool isFlagEnabled(enumType flag) const
        {
            return flags >> static_cast<unsigned int>(flag) & 1U;
        }

        /**
         * @return An unsigned integer representation of the status of each feature
         */
        unsigned int getFlags() const
        {
            return flags;
        }

        void resetFlags()
        {
            flags = 0;
        }

    private:
        unsigned int flags = 0;
    };

    /***************************************************************************/
    /* Misc Helper functions                                                   */
    /***************************************************************************/

    /**
     * Utility access wrapper and formatter for getAllMaterialNames and getAllMaterialNamesSize
     * @param apiManager [input] the api manager to request data from
     * @return all bulk material names as a vector of strings
     */
    inline std::vector<std::string> getAllBulkMaterialNamesAsVector(NApiCore::IApi* apiManager)
    {
        auto* particleManager = dynamic_cast<NApiCore::IApiManager_1_1*>(apiManager)->getParticleManager();

        std::vector<std::string> allNames;
        if (particleManager)
        {
            char* materialNames = new char[particleManager->getAllMaterialNamesSize()];
            char* matNameIter = materialNames;
            int numberOfMaterials = particleManager->getAllMaterialNames(materialNames);
            allNames.reserve(numberOfMaterials);

            for (int i = 0; i < numberOfMaterials; ++i)
            {
                allNames.push_back(std::string(matNameIter));
                matNameIter += static_cast<int>(allNames.back().size() + 1); // plus 1 indicates null terminator
            }
            delete[] materialNames;
        }
        return allNames;
    }

    /**
    * Utility access wrapper and formatter for getAllParticleTypeNames and getAllParticleTypeNamesSize
    * @param apiManager [input] the api manager to request data from
    * @return all particle type names as a vector of strings
    */
    inline std::vector<std::string> getAllParticleTypeNamesVector(NApiCore::IApi* apiManager)
    {
        auto* particleManager = dynamic_cast<NApiCore::IApiManager_1_1*>(apiManager)->getParticleManager();

        std::vector<std::string> allNames;
        if (particleManager)
        {
            char* particleTypeNames = new char[particleManager->getAllParticleTypeNamesSize()];
            char* particleTypeNameIter = particleTypeNames;
            int numberOfParticleTypes = particleManager->getAllParticleTypeNames(particleTypeNames);
            allNames.reserve(numberOfParticleTypes);

            for (int i = 0; i < numberOfParticleTypes; ++i)
            {
                allNames.push_back(std::string(particleTypeNameIter));
                particleTypeNameIter += static_cast<int>(allNames.back().size() + 1); // plus 1 indicates null terminator
            }
            delete[] particleTypeNames;
        }
        return allNames;
    }

    /**
    * Utility access wrapper and formatter for getAllMaterialNames and getAllMaterialNamesSize
    * @param apiManager [input] the api manager to request data from
    * @return all equipment material names as a vector of strings
    */
    inline std::vector<std::string> getAllEquipMaterialNamesAsVector(NApiCore::IApi* apiManager)
    {
        auto* geometryManager = dynamic_cast<NApiCore::IApiManager_1_1*>(apiManager)->getGeometryManager();

        std::vector<std::string> allNames;
        if (geometryManager)
        {
            char* materialNames = new char[geometryManager->getAllMaterialNamesSize()];
            char* matNameIter = materialNames;
            int numberOfMaterials = geometryManager->getAllMaterialNames(materialNames);
            allNames.reserve(numberOfMaterials);

            for (int i = 0; i < numberOfMaterials; ++i)
            {
                allNames.push_back(std::string(matNameIter));
                matNameIter += static_cast<int>(allNames.back().size() + 1); // plus 1 indicates null terminator
            }
            delete[] materialNames;
        }
        return allNames;
    }

    /**
    * Utility access wrapper and formatter for getAllGeometryNames and getAllGeometryNamesSize
    * @param apiManager [input] the api manager to request data from
    * @return all geometry names as a vector of strings
    */
    inline std::vector<std::string> getAllGeometryNamesAsVector(NApiCore::IApi* apiManager)
    {
        auto* geometryManager = dynamic_cast<NApiCore::IApiManager_1_1*>(apiManager)->getGeometryManager();

        std::vector<std::string> allNames;
        if (geometryManager)
        {
            char* geometryNames = new char[geometryManager->getAllGeometryNamesSize()];
            char* geomNameIter = geometryNames;
            int numberOfGeometries = geometryManager->getAllGeometryNames(geometryNames);
            allNames.reserve(numberOfGeometries);

            for (int i = 0; i < numberOfGeometries; ++i)
            {
                allNames.push_back(std::string(geomNameIter));
                geomNameIter += static_cast<int>(allNames.back().size() + 1); // plus 1 indicates null terminator
            }
            delete[] geometryNames;
        }
        return allNames;
    }

    /**
    * Helper function to safely retrieve geometry triangle nodes from the geometry api manager.
    * @param geometryManager
    * @param geomName
    * @return triangle nodes for the given geometry
    */
    inline std::vector<SGeomTriangleNode> getGeometryTriangleNodes(NApiCore::IApi* apiManager,
                                                                   const CSimpleString& geomName)
    {
        std::vector<SGeomTriangleNode> nodes;

        auto* geometryManager = dynamic_cast<NApiCore::IApiManager_1_1*>(apiManager)->getGeometryManager();
        if (!geometryManager)
        {
            return nodes;
        }

        const unsigned int* nodesDescription(geometryManager->getAllTriangleNodes(geomName.getString()));
        const auto sizeBuffer(geometryManager->getSizeTriangleNodeBuffer(geomName.getString()));



        if (nodesDescription == nullptr)
            return nodes;

        nodes.reserve(sizeBuffer / 3);

        for (unsigned int i{ 0 }; i < sizeBuffer; i += 3)
        {
            nodes.emplace_back(nodesDescription[i], nodesDescription[i + 1], nodesDescription[i + 2]);
        }

        return nodes;
    }
}

#endif // HELPERSV3_8_0_H
