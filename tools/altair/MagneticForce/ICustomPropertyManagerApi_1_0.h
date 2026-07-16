#ifndef ICUSTOMPROPERTYMANAGERAPI_1_0_H
#define ICUSTOMPROPERTYMANAGERAPI_1_0_H

#include "IApi.h"

namespace NApiCore
{
    /**
     * The ICustomPropertyManagerApi_1_0 interface provides basic access to the
     * the configured custom property data for one of four different custom
     * property collections (particle, geometry element, contact, simulation).
     *
     * It allows the retrieval of meta-data details for all properties
     * registered with the system for the corresponding property collection.
     *
     * There are 2 ways of identifying a custom property uniquely:
     *     Name
     *     Index
     *
     * Most methods are provided in two forms; one taking a name
     * and another taking an index.  The index based method is
     * always faster than the name based method.  However the index
     * can change if the deck is reloaded or EDEM is restarted, it
     * should only be cached for short term use.
     *
     * NAME:     Custom Property Manager
     * ID:       EApiId::eContactCustomPropertyManager    (4)
     *           EApiId::eGeometryCustomPropertyManager   (5)
     *           EApiId::eParticleCustomPropertyManager   (6)
     *           EApiId::eSimulationCustomPropertyManager (7)
     * VERSION:  1.0
     */
    class ICustomPropertyManagerApi_1_0 : public IApi
    {
    public:

        /**
         * Encompasses the details of a single property definition.
         */
        struct SPropertyData
        {
            /**
             * The name of the custom property
             */
            char m_name[NApi::CUSTOM_PROP_MAX_NAME_LENGTH];

            /**
             * Index of property within collection, also
             * acts as a form of unique ID within the collection
             */
            unsigned int m_index;

            /**
             * The property category (Particle, Geometry element etc.)
             */
            NApi::EPluginPropertyCategory m_category;

            /**
             * Data type for the property (currently always double)
             */
            NApi::EPluginPropertyDataTypes m_dataType;

            /**
             * Number of elements that make up the property
             */
            unsigned int m_numberOfElements;

            /**
             * Unit type of the property
             */
            NApi::EPluginPropertyUnitTypes m_unitType;

            /**
             * Finalised properties have data storage
             * allocated for them already, tentative
             * properties do not
             */
            bool m_finalised;
        };

        /**
         * Constructor, does nothing.
         */
        ICustomPropertyManagerApi_1_0() {};

        /**
         * Destructor, does nothing.
         */
        virtual ~ICustomPropertyManagerApi_1_0() {};

        /**
         * Returns the number of custom properties registered
         * with the collection
         * @return The number of properties
         */
        virtual unsigned int getNumProperties() = 0;

        /**
         * Given a property name returns the index of the property.
         *
         * @param name The name of the property to retrieve the index for
         * @return The ID or NApi::NO_ID if the property does not exist
         */
        virtual unsigned int getPropertyIndex(const char* name) = 0;

        /**
         * Populates data with the meta-data for the property with
         * the supplied index.
         *
         * If the supplied index is NApi::NO_ID this method returns
         * false and does not change data.
         *
         * @param index The index of the property to retrieve data for
         * @param data (RETURN VALUE)
         *             Populated with the properties meta-data
         * @return true if id corresponds to a valid property, else false.
         */
        virtual bool getPropertyMetaData(unsigned int index,
                                         SPropertyData& data) = 0;

        /**
         * Populates data with the meta-data for the property with
         * the supplied name.
         *
         * @param name The name of the property to retrieve data for
         * @param data (RETURN VALUE)
         *             Populated with the properties meta-data
         * @return true if name corresponds to a valid property, else false.
         */
        virtual bool getPropertyMetaData(const char* name, SPropertyData& data) = 0;

    };
};

#endif // ICUSTOMPROPERTYMANAGERAPI_1_0_H
