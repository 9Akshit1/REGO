#ifndef HELPERS_H
#define HELPERS_H

/***************************************************************************/
/* This file contains a number of helper functions and classes used        */
/* to speed up calculations.  It does not form part of the published       */
/* EDEM API. You should copy it to the same directory as the rest of your  */
/* plugin source files.  These functions and methods are not versioned and */
/* may change between releases of EDEM.                                    */
/*                                                                         */
/* All functions and declarations are contained purely within this header  */
/***************************************************************************/

#include <istream>
#include <fstream>
#include <math.h>

/***************************************************************************/
/* Forward declarations of classes in this file                            */
/***************************************************************************/
class CSimple3DVector;
class CSimple3DPoint;
class CSimple3x3Matrix;

/***************************************************************************/
/* Constant definitions of use in calculations                             */
/***************************************************************************/

const double PI = 3.141592654;
const double DOUBLE_UNDERFLOW = 1e-25;
const double REALLY_REALLY_ZERO = 1e-40;

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
template <class T>
bool isZero(const T val)
{
    if(val < DOUBLE_UNDERFLOW && val > (-DOUBLE_UNDERFLOW))
    {
        return true;
    }
    else
    {
        return false;
    }
}

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
template <class T>
inline bool isReallyReallyZero(const T val, const T tolerance = REALLY_REALLY_ZERO)
{
    if(val <= tolerance && val >= (-tolerance))
    {
        return true;
    }
    else
    {
        return false;
    }
}

/**
 * Compares 2 doubles.  As doubles produce small variations due to
 * rounding this method allows the difference to be up to
 * REALLY_REALLY_ZERO (or another user supplied value)
 * @param valA The first value to check
 * @param valB The second value to check
 * @param tolerance The tolerance to check to
 * @return bool True if the values are the same (within the tolerance)
 */
template <class T>
inline bool areEqual(const T valA, const T valB, const T tolerance = REALLY_REALLY_ZERO)
{
    if(!isReallyReallyZero(valB, tolerance))
    {
        // valB is not zero
        return ( fabs(valA/valB - 1.0) < 1e-12 );
    }
    else if(!isReallyReallyZero(valA, tolerance))
    {
        // valA is not zero
        return ( fabs(valB/valA - 1.0) < 1e-12 );
    }
    else
    {
        // Both values are effectivly zero so they are the same
        return true;
    }
}

/***************************************************************************/
/* Class definitions for representation of matrices, vectors and points in */
/* 3D space                                                                */
/***************************************************************************/

/**
 * The CSimple3DVector class represents a vector in 3D space.
 * Points and vectors differ in the operations that can be performed on them
 */
class CSimple3DVector
{
public:
    CSimple3DVector() {m_nX = 0; m_nY = 0; m_nZ = 0;}

    CSimple3DVector(const CSimple3DVector &vect);

    CSimple3DVector(double dx, double dy, double dz) {m_nX = dx; m_nY = dy; m_nZ = dz;}

    virtual ~CSimple3DVector() {}

    inline CSimple3DVector  operator+(const CSimple3DVector &vector) const;
    inline CSimple3DVector& operator+=(const CSimple3DVector &vector);

    inline CSimple3DVector  operator-(const CSimple3DVector &vector) const;
    inline CSimple3DVector  operator-() const;
    inline CSimple3DVector& operator-=(const CSimple3DVector &vector);

    inline CSimple3DVector  operator*(const double multValue) const;
    inline CSimple3DVector  operator*(const CSimple3x3Matrix& mat) const;
    inline CSimple3DVector& operator*=(const double multValue);
    inline CSimple3DVector& operator*=(const CSimple3x3Matrix& mat);

    inline CSimple3DVector  operator/(const double divValue) const;
    inline CSimple3DVector& operator/=(const double divValue);

    inline bool operator==(const CSimple3DVector& vector) const;
    inline bool operator!=(const CSimple3DVector& vector) const;

    inline CSimple3DVector  normalise();
    inline CSimple3DVector  cross(const CSimple3DVector &vector) const;
    inline double           dot(const CSimple3DVector &vector) const;
    inline double           length() const        {return sqrt(m_nX * m_nX + m_nY * m_nY + m_nZ * m_nZ);}
    inline double           lengthSquared() const {return m_nX * m_nX + m_nY * m_nY + m_nZ * m_nZ;}

    inline double           dx() const            {return m_nX;}
    inline double           dy() const            {return m_nY;}
    inline double           dz() const            {return m_nZ;}
    inline void             setdx(double dx)      {m_nX = dx;}
    inline void             setdy(double dy)      {m_nY = dy;}
    inline void             setdz(double dz)      {m_nZ = dz;}

private:
    virtual void CheckForUnderflow();
    double m_nX, m_nY, m_nZ;
};

/**
 * The CSimple3DPoint class represents a point in 3D space
 * Points and vectors differ in the operations that can be performed on them
 */
class CSimple3DPoint
{
public:
    CSimple3DPoint() {m_nX = 0; m_nY = 0; m_nZ = 0; }

    CSimple3DPoint(const CSimple3DPoint &point);

    CSimple3DPoint(double in_x, double in_y, double in_z);

    virtual ~CSimple3DPoint() {}

    inline CSimple3DPoint  operator+(const CSimple3DVector &vect) const;
    inline CSimple3DPoint& operator+=(const CSimple3DVector &vect);

    inline CSimple3DVector operator-(const CSimple3DPoint &point) const;
    inline CSimple3DPoint  operator-(const CSimple3DVector &vector) const;
    inline CSimple3DPoint& operator-=(const CSimple3DVector &vect);

    inline CSimple3DPoint  operator*( double multValue) const;
    inline CSimple3DPoint& operator*=( double multValue);

    inline CSimple3DPoint  operator/( double divValue) const;
    inline CSimple3DPoint& operator/=( double divValue);

    inline bool            operator==(const CSimple3DPoint &point) const;

    inline double          distance(const CSimple3DPoint &point) const;

    inline double          x() const {return m_nX;}
    inline double          y() const {return m_nY;}
    inline double          z() const {return m_nZ;}
    inline void            setX(double x)    {m_nX = x;}
    inline void            setY(double y)    {m_nY = y;}
    inline void            setZ(double z)    {m_nZ = z;}

    friend std::istream& operator>>(std::istream &stream, CSimple3DPoint &point);

private:
    inline void CheckForUnderflow();

    double m_nX, m_nY, m_nZ;
};

/**
 * The CSimple3x3Matrix class represents a 3x3 matrix.
 * Various operations to access and manipulate the matrix are provided
 */
class CSimple3x3Matrix
{
public:
    CSimple3x3Matrix();

    CSimple3x3Matrix(const CSimple3x3Matrix &mat);

    CSimple3x3Matrix (double dxx, double dxy, double dxz,
                      double dyx, double dyy, double dyz,
                      double dzx, double dzy, double dzz);

    CSimple3x3Matrix(const CSimple3DVector &vector, double rotAngle);

    virtual ~CSimple3x3Matrix() {}

    inline CSimple3x3Matrix  operator+(const CSimple3x3Matrix &mat) const;
    inline CSimple3x3Matrix& operator+=(const CSimple3x3Matrix &mat);

    inline CSimple3x3Matrix  operator-(const CSimple3x3Matrix &mat) const;
    inline CSimple3x3Matrix& operator-=(const CSimple3x3Matrix &mat);

    inline CSimple3x3Matrix  operator-() const;

    inline CSimple3x3Matrix  operator*(const double multValue) const;
    inline CSimple3x3Matrix  operator*(const CSimple3x3Matrix &mat) const;
    inline CSimple3x3Matrix& operator*=(const double multValue);
    inline CSimple3x3Matrix& operator*=(const CSimple3x3Matrix &mat);

    inline CSimple3x3Matrix  operator/(const double divValue) const;
    inline CSimple3x3Matrix& operator/=(const double divValue);

    inline double            det() const;
    inline CSimple3x3Matrix  inv() const;
    inline CSimple3x3Matrix  transpose() const;

    inline double  dxx() const        {return m_nXX;}
    inline double  dxy() const        {return m_nXY;}
    inline double  dxz() const        {return m_nXZ;}
    inline double  dyx() const        {return m_nYX;}
    inline double  dyy() const        {return m_nYY;}
    inline double  dyz() const        {return m_nYZ;}
    inline double  dzx() const        {return m_nZX;}
    inline double  dzy() const        {return m_nZY;}
    inline double  dzz() const        {return m_nZZ;}
    inline void    setdxx(double dxx) {m_nXX = dxx;}
    inline void    setdxy(double dxy) {m_nXY = dxy;}
    inline void    setdxz(double dxz) {m_nXZ = dxz;}
    inline void    setdyx(double dyx) {m_nYX = dyx;}
    inline void    setdyy(double dyy) {m_nYY = dyy;}
    inline void    setdyz(double dyz) {m_nYZ = dyz;}
    inline void    setdzx(double dzx) {m_nZX = dzx;}
    inline void    setdzy(double dzy) {m_nZY = dzy;}
    inline void    setdzz(double dzz) {m_nZZ = dzz;}

private:
    inline virtual void CheckForUnderflow();
    double m_nXX, m_nXY, m_nXZ, m_nYX, m_nYY, m_nYZ, m_nZX, m_nZY, m_nZZ;
};

/***************************************************************************/
/* Inline Implementations of all CSimple3DPoint methods                    */
/***************************************************************************/

inline CSimple3DPoint::CSimple3DPoint(const CSimple3DPoint &point)
{
    m_nX = point.m_nX;
    m_nY = point.m_nY;
    m_nZ = point.m_nZ;

    CheckForUnderflow();
}

inline CSimple3DPoint::CSimple3DPoint(double in_x, double in_y, double in_z)
{
    m_nX = in_x;
    m_nY = in_y;
    m_nZ = in_z;

    CheckForUnderflow();
}

inline void CSimple3DPoint::CheckForUnderflow()
{
    if(isZero(m_nX)) m_nX = 0;
    if(isZero(m_nY)) m_nY = 0;
    if(isZero(m_nZ)) m_nZ = 0;
}

inline CSimple3DPoint CSimple3DPoint::operator+(const CSimple3DVector &vect) const
{
    CSimple3DPoint retVal;

    retVal.setX(m_nX + vect.dx());
    retVal.setY(m_nY + vect.dy());
    retVal.setZ(m_nZ + vect.dz());

    return retVal;

}

inline CSimple3DPoint& CSimple3DPoint::operator+=(const CSimple3DVector &vect)
{
    m_nX += vect.dx();
    m_nY += vect.dy();
    m_nZ += vect.dz();

    CheckForUnderflow();

    return *this;
}

inline CSimple3DPoint& CSimple3DPoint::operator-=(const CSimple3DVector &vect)
{
    m_nX -= vect.dx();
    m_nY -= vect.dy();
    m_nZ -= vect.dz();

    CheckForUnderflow();

    return *this;
}

inline CSimple3DVector CSimple3DPoint::operator-(const CSimple3DPoint &point) const
{
    CSimple3DVector vector(m_nX - point.m_nX, m_nY - point.m_nY, m_nZ - point.m_nZ);
    return vector;
}

inline CSimple3DPoint CSimple3DPoint::operator-(const CSimple3DVector &vector) const
{
    CSimple3DPoint point(m_nX - vector.dx(), m_nY - vector.dy(), m_nZ - vector.dz());
    return point;
}

inline CSimple3DPoint CSimple3DPoint::operator/(double divValue) const
{
    CSimple3DPoint retVal;

    if(!isZero(divValue))
    {
        retVal.setX (m_nX / divValue);
        retVal.setY (m_nY / divValue);
        retVal.setZ (m_nZ / divValue);
    }
    else
    {
        retVal.setX (9E30);
        retVal.setY (9E30);
        retVal.setZ (9E30);
    }

    return retVal;
}

inline CSimple3DPoint& CSimple3DPoint::operator/=(double divValue)
{
    if(!isZero(divValue))
    {
        m_nX /= divValue;
        m_nY /= divValue;
        m_nZ /= divValue;
    }
    else
    {
        m_nX = 9E30;
        m_nY = 9E30;
        m_nZ = 9E30;
    }

    CheckForUnderflow();

    return *this;
}

inline CSimple3DPoint CSimple3DPoint::operator*(double multValue) const
{
    CSimple3DPoint retVal;

    retVal.setX (m_nX * multValue);
    retVal.setY (m_nY * multValue);
    retVal.setZ (m_nZ * multValue);

    return retVal;
}

inline CSimple3DPoint& CSimple3DPoint::operator*=(double multValue)
{
    m_nX *= multValue;
    m_nY *= multValue;
    m_nZ *= multValue;

    CheckForUnderflow();

    return *this;
}

inline bool CSimple3DPoint::operator==(const CSimple3DPoint &point)  const
{
    if(isZero(m_nX - point.m_nX) && isZero(m_nY - point.m_nY) && isZero(m_nZ - point.m_nZ))
    {
        return true;
    }

    return false;
}

inline std::istream& operator>>(std::istream &stream, CSimple3DPoint &point)
{
    stream >> point.m_nX >> point.m_nY >> point.m_nZ;

    return stream;
}

inline double CSimple3DPoint::distance(const CSimple3DPoint &point) const
{
    return sqrt((m_nX-point.x())*(m_nX-point.x()) + (m_nY-point.y())*(m_nY-point.y()) + (m_nZ-point.z())*(m_nZ-point.z()));
}

/***************************************************************************/
/* Inline Implementations of all CSimple3DVector methods                   */
/***************************************************************************/

inline CSimple3DVector::CSimple3DVector(const CSimple3DVector &vect)
{
    m_nX = vect.m_nX;
    m_nY = vect.m_nY;
    m_nZ = vect.m_nZ;

    CheckForUnderflow();
}

inline CSimple3DVector CSimple3DVector::normalise()
{
    double nLength = length();

    if(!isZero(nLength)) //only normalise if length isn't zero.
    {
        m_nX /= nLength;
        m_nY /= nLength;
        m_nZ /= nLength;
    }

    CheckForUnderflow();

    return *this;
}

inline void CSimple3DVector::CheckForUnderflow()
{
    if(isZero(m_nX)) m_nX = 0;
    if(isZero(m_nY)) m_nY = 0;
    if(isZero(m_nZ)) m_nZ = 0;
}

inline CSimple3DVector CSimple3DVector::operator+(const CSimple3DVector &vector) const
{
    CSimple3DVector retVal;

    retVal.setdx( vector.m_nX + m_nX);
    retVal.setdy( vector.m_nY + m_nY);
    retVal.setdz( vector.m_nZ + m_nZ);

    return retVal;
}

inline CSimple3DVector& CSimple3DVector::operator+=(const CSimple3DVector &vector)
{
    m_nX += vector.m_nX;
    m_nY += vector.m_nY;
    m_nZ += vector.m_nZ;

    CheckForUnderflow();

    return *this;
}

inline CSimple3DVector CSimple3DVector::operator-(const CSimple3DVector &vector) const
{
    CSimple3DVector retVal;

    retVal.setdx( m_nX - vector.m_nX);
    retVal.setdy( m_nY - vector.m_nY);
    retVal.setdz( m_nZ - vector.m_nZ);

    return retVal;
}

inline CSimple3DVector& CSimple3DVector::operator-=(const CSimple3DVector &vector)
{
    m_nX -= vector.m_nX;
    m_nY -= vector.m_nY;
    m_nZ -= vector.m_nZ;

    CheckForUnderflow();

    return *this;
}

inline CSimple3DVector CSimple3DVector::operator-() const
{
    return  CSimple3DVector(-m_nX, -m_nY, -m_nZ);
}

inline CSimple3DVector CSimple3DVector::operator*(const double multValue) const
{
    CSimple3DVector retVal;

    retVal.setdx( m_nX * multValue);
    retVal.setdy( m_nY* multValue);
    retVal.setdz( m_nZ * multValue);

    return retVal;
}

inline CSimple3DVector CSimple3DVector::operator*(const CSimple3x3Matrix& mat) const
{
    CSimple3DVector retVect;

    retVect.setdx( m_nX * mat.dxx() + m_nY * mat.dxy() + m_nZ * mat.dxz());
    retVect.setdy( m_nX * mat.dyx() + m_nY * mat.dyy() + m_nZ * mat.dyz());
    retVect.setdz( m_nX * mat.dzx() + m_nY * mat.dzy() + m_nZ * mat.dzz());

    return retVect;
}

inline CSimple3DVector& CSimple3DVector::operator*=(const double multValue)
{
    m_nX *= multValue;
    m_nY *= multValue;
    m_nZ *= multValue;

    CheckForUnderflow();

    return *this;
}

inline CSimple3DVector& CSimple3DVector::operator*=(const CSimple3x3Matrix& mat)
{
    CSimple3DVector tmp(*this); 
    m_nX = tmp.m_nX * mat.dxx() + tmp.m_nY * mat.dxy() + tmp.m_nZ * mat.dxz();
    m_nY = tmp.m_nX * mat.dyx() + tmp.m_nY * mat.dyy() + tmp.m_nZ * mat.dyz();
    m_nZ = tmp.m_nX * mat.dzx() + tmp.m_nY * mat.dzy() + tmp.m_nZ * mat.dzz();

    CheckForUnderflow();

    return *this;
}

inline CSimple3DVector CSimple3DVector::operator/(const double divValue) const
{
    CSimple3DVector retVal;

    if(!isZero(divValue))
    {
        retVal.setdx( m_nX / divValue);
        retVal.setdy( m_nY  / divValue);
        retVal.setdz( m_nZ  / divValue);
    }
    else
    {
        retVal.setdx( 9E30);
        retVal.setdy( 9E30);
        retVal.setdz( 9E30);
    }

    return retVal;
}

inline CSimple3DVector& CSimple3DVector::operator/=(const double divValue)
{
    if(!isZero(divValue))
    {
        m_nX /= divValue;
        m_nY /= divValue;
        m_nZ /= divValue;
    }
    else
    {
        m_nX = 9E30;
        m_nY = 9E30;
        m_nZ = 9E30;
    }

    CheckForUnderflow();

    return *this;
}

inline bool CSimple3DVector::operator==(const CSimple3DVector& vector) const
{
    return (areEqual(m_nX, vector.m_nX)) &&
           (areEqual(m_nY, vector.m_nY)) &&
           (areEqual(m_nZ, vector.m_nZ));
}


inline bool CSimple3DVector::operator!=(const CSimple3DVector& vector) const
{
    return !(*this == vector);
}

inline CSimple3DVector CSimple3DVector::cross(const CSimple3DVector &vector) const
{
    CSimple3DVector retVect;

    retVect.setdx( m_nY * vector.m_nZ - m_nZ * vector.m_nY );
    retVect.setdy( m_nZ * vector.m_nX - m_nX * vector.m_nZ );
    retVect.setdz( m_nX * vector.m_nY - m_nY * vector.m_nX );

    return retVect;
}

inline double CSimple3DVector::dot(const CSimple3DVector &vector) const
{
    return m_nX * vector.m_nX + m_nY * vector.m_nY + m_nZ * vector.m_nZ;
}

/***************************************************************************/
/* Inline Implementations of all CSimple3x3Matrix methods                  */
/***************************************************************************/

inline CSimple3x3Matrix::CSimple3x3Matrix() :
                         m_nXX(1),
                         m_nXY(0),
                         m_nXZ(0),
                         m_nYX(0),
                         m_nYY(1),
                         m_nYZ(0),
                         m_nZX(0),
                         m_nZY(0),
                         m_nZZ(1)
{
    ;
}


inline CSimple3x3Matrix::CSimple3x3Matrix(double dxx, double dxy, double dxz,
                                          double dyx, double dyy, double dyz,
                                          double dzx, double dzy, double dzz)  :
                         m_nXX(dxx),
                         m_nXY(dxy),
                         m_nXZ(dxz),
                         m_nYX(dyx),
                         m_nYY(dyy),
                         m_nYZ(dyz),
                         m_nZX(dzx),
                         m_nZY(dzy),
                         m_nZZ(dzz)
{
    ;
}

inline CSimple3x3Matrix::CSimple3x3Matrix(const CSimple3x3Matrix &mat)
{
    m_nXX = mat.m_nXX;
    m_nXY = mat.m_nXY;
    m_nXZ = mat.m_nXZ;
    m_nYX = mat.m_nYX;
    m_nYY = mat.m_nYY;
    m_nYZ = mat.m_nYZ;
    m_nZX = mat.m_nZX;
    m_nZY = mat.m_nZY;
    m_nZZ = mat.m_nZZ;

    CheckForUnderflow();
}

inline CSimple3x3Matrix::CSimple3x3Matrix(const CSimple3DVector &vector, double rotAngle)
{
    double c = cos(rotAngle);
    double s = sin(rotAngle);

    m_nXX = 1 + ( 1 - c ) * ( vector.dx() * vector.dx() - 1 );
    m_nXY = -vector.dz() * s + ( 1 - c ) * vector.dx() * vector.dy();
    m_nXZ = vector.dy() * s + ( 1 - c ) * vector.dx() * vector.dz();
    m_nYX = vector.dz() * s + ( 1 - c ) * vector.dx() * vector.dy();
    m_nYY = 1 + ( 1 - c ) * ( vector.dy() * vector.dy() - 1 );
    m_nYZ = -vector.dx() * s + ( 1 - c ) * vector.dy() * vector.dz();
    m_nZX = -vector.dy() * s + ( 1 - c ) * vector.dx() * vector.dz();
    m_nZY = vector.dx() * s + ( 1 - c ) * vector.dy() * vector.dz();
    m_nZZ = 1 + ( 1 - c ) * ( vector.dz() * vector.dz() - 1 );

    CheckForUnderflow();

}

inline void CSimple3x3Matrix::CheckForUnderflow()
{
    if(isZero(m_nXX)) m_nXX = 0;
    if(isZero(m_nXY)) m_nXY = 0;
    if(isZero(m_nXZ)) m_nXZ = 0;
    if(isZero(m_nYX)) m_nYX = 0;
    if(isZero(m_nYY)) m_nYY = 0;
    if(isZero(m_nYZ)) m_nYZ = 0;
    if(isZero(m_nZX)) m_nZX = 0;
    if(isZero(m_nZY)) m_nZY = 0;
    if(isZero(m_nZZ)) m_nZZ = 0;
}

inline CSimple3x3Matrix CSimple3x3Matrix::operator+(const CSimple3x3Matrix &mat) const
{
    CSimple3x3Matrix retVal;

    retVal.setdxx( mat.m_nXX + m_nXX);
    retVal.setdxy( mat.m_nXY + m_nXY);
    retVal.setdxz( mat.m_nXZ + m_nXZ);
    retVal.setdyx( mat.m_nYX + m_nYX);
    retVal.setdyy( mat.m_nYY + m_nYY);
    retVal.setdyz( mat.m_nYZ + m_nYZ);
    retVal.setdzx( mat.m_nZX + m_nZX);
    retVal.setdzy( mat.m_nZY + m_nZY);
    retVal.setdzz( mat.m_nZZ + m_nZZ);

    return retVal;
}

inline CSimple3x3Matrix& CSimple3x3Matrix::operator+=(const CSimple3x3Matrix &mat)
{
    m_nXX += mat.m_nXX;
    m_nXY += mat.m_nXY;
    m_nXZ += mat.m_nXZ;
    m_nYX += mat.m_nYX;
    m_nYY += mat.m_nYY;
    m_nYZ += mat.m_nYZ;
    m_nZX += mat.m_nZX;
    m_nZY += mat.m_nZY;
    m_nZZ += mat.m_nZZ;

    CheckForUnderflow();

    return *this;
}

inline CSimple3x3Matrix CSimple3x3Matrix::operator-(const CSimple3x3Matrix &mat) const
{
    CSimple3x3Matrix retVal;

    retVal.setdxx( m_nXX - mat.m_nXX);
    retVal.setdxy( m_nXY - mat.m_nXY);
    retVal.setdxz( m_nXZ - mat.m_nXZ);
    retVal.setdyx( m_nYX - mat.m_nYX);
    retVal.setdyy( m_nYY - mat.m_nYY);
    retVal.setdyz( m_nYZ - mat.m_nYZ);
    retVal.setdzx( m_nZX - mat.m_nZX);
    retVal.setdzy( m_nZY - mat.m_nZY);
    retVal.setdzz( m_nZZ - mat.m_nZZ);

    return retVal;
}

inline CSimple3x3Matrix& CSimple3x3Matrix::operator-=(const CSimple3x3Matrix &mat)
{
    m_nXX -= mat.m_nXX;
    m_nXY -= mat.m_nXY;
    m_nXZ -= mat.m_nXZ;
    m_nYX -= mat.m_nYX;
    m_nYY -= mat.m_nYY;
    m_nYZ -= mat.m_nYZ;
    m_nZX -= mat.m_nZX;
    m_nZY -= mat.m_nZY;
    m_nZZ -= mat.m_nZZ;

    CheckForUnderflow();

    return *this;
}

inline CSimple3x3Matrix CSimple3x3Matrix::operator*(const double multValue) const
{
    CSimple3x3Matrix retVal;

    retVal.setdxx( m_nXX  * multValue);
    retVal.setdxy( m_nXY  * multValue);
    retVal.setdxz( m_nXZ  * multValue);
    retVal.setdyx( m_nYX  * multValue);
    retVal.setdyy( m_nYY  * multValue);
    retVal.setdyz( m_nYZ  * multValue);
    retVal.setdzx( m_nZX  * multValue);
    retVal.setdzy( m_nZY  * multValue);
    retVal.setdzz( m_nZZ  * multValue);

    return retVal;
}

inline CSimple3x3Matrix CSimple3x3Matrix::operator*(const CSimple3x3Matrix &mat) const
{
    CSimple3x3Matrix retVal;

    retVal.setdxx( m_nXX * mat.m_nXX + m_nXY * mat.m_nYX + m_nXZ * mat.m_nZX);
    retVal.setdxy( m_nXX * mat.m_nXY + m_nXY * mat.m_nYY + m_nXZ * mat.m_nZY);
    retVal.setdxz( m_nXX * mat.m_nXZ + m_nXY * mat.m_nYZ + m_nXZ * mat.m_nZZ);
    retVal.setdyx( m_nYX * mat.m_nXX + m_nYY * mat.m_nYX + m_nYZ * mat.m_nZX);
    retVal.setdyy( m_nYX * mat.m_nXY + m_nYY * mat.m_nYY + m_nYZ * mat.m_nZY);
    retVal.setdyz( m_nYX * mat.m_nXZ + m_nYY * mat.m_nYZ + m_nYZ * mat.m_nZZ);
    retVal.setdzx( m_nZX * mat.m_nXX + m_nZY * mat.m_nYX + m_nZZ * mat.m_nZX);
    retVal.setdzy( m_nZX * mat.m_nXY + m_nZY * mat.m_nYY + m_nZZ * mat.m_nZY);
    retVal.setdzz( m_nZX * mat.m_nXZ + m_nZY * mat.m_nYZ + m_nZZ * mat.m_nZZ);

    return retVal;
}

inline CSimple3x3Matrix& CSimple3x3Matrix::operator*=(const double multValue)
{
    m_nXX  *= multValue;
    m_nXY  *= multValue;
    m_nXZ  *= multValue;
    m_nYX  *= multValue;
    m_nYY  *= multValue;
    m_nYZ  *= multValue;
    m_nZX  *= multValue;
    m_nZY  *= multValue;
    m_nZZ  *= multValue;

    CheckForUnderflow();

    return *this;
}

inline CSimple3x3Matrix& CSimple3x3Matrix::operator*=(const CSimple3x3Matrix &mat)
{
    CSimple3x3Matrix tmp(*this);
    m_nXX = tmp.m_nXX * mat.m_nXX + tmp.m_nXY * mat.m_nYX + tmp.m_nXZ * mat.m_nZX;
    m_nXY = tmp.m_nXX * mat.m_nXY + tmp.m_nXY * mat.m_nYY + tmp.m_nXZ * mat.m_nZY;
    m_nXZ = tmp.m_nXX * mat.m_nXZ + tmp.m_nXY * mat.m_nYZ + tmp.m_nXZ * mat.m_nZZ;
    m_nYX = tmp.m_nYX * mat.m_nXX + tmp.m_nYY * mat.m_nYX + tmp.m_nYZ * mat.m_nZX;
    m_nYY = tmp.m_nYX * mat.m_nXY + tmp.m_nYY * mat.m_nYY + tmp.m_nYZ * mat.m_nZY;
    m_nYZ = tmp.m_nYX * mat.m_nXZ + tmp.m_nYY * mat.m_nYZ + tmp.m_nYZ * mat.m_nZZ;
    m_nZX = tmp.m_nZX * mat.m_nXX + tmp.m_nZY * mat.m_nYX + tmp.m_nZZ * mat.m_nZX;
    m_nZY = tmp.m_nZX * mat.m_nXY + tmp.m_nZY * mat.m_nYY + tmp.m_nZZ * mat.m_nZY;
    m_nZZ = tmp.m_nZX * mat.m_nXZ + tmp.m_nZY * mat.m_nYZ + tmp.m_nZZ * mat.m_nZZ;

    CheckForUnderflow();

    return *this;
}

inline CSimple3x3Matrix CSimple3x3Matrix::operator/(const double divValue) const
{
    CSimple3x3Matrix retVal;

    if(!isZero(divValue))
    {
        retVal.setdxx( m_nXX  / divValue);
        retVal.setdxy( m_nXY  / divValue);
        retVal.setdxz( m_nXZ  / divValue);
        retVal.setdyx( m_nYX  / divValue);
        retVal.setdyy( m_nYY  / divValue);
        retVal.setdyz( m_nYZ  / divValue);
        retVal.setdzx( m_nZX  / divValue);
        retVal.setdzy( m_nZY  / divValue);
        retVal.setdzz( m_nZZ  / divValue);
    }
    else
    {
        retVal.setdxx( 9E30);
        retVal.setdxy( 9E30);
        retVal.setdxz( 9E30);
        retVal.setdyx( 9E30);
        retVal.setdyy( 9E30);
        retVal.setdyz( 9E30);
        retVal.setdzx( 9E30);
        retVal.setdzy( 9E30);
        retVal.setdzz( 9E30);
    }

    return retVal;
}

inline CSimple3x3Matrix& CSimple3x3Matrix::operator/=(const double divValue)
{
    if(!isZero(divValue))
    {
        m_nXX  /= divValue;
        m_nXY  /= divValue;
        m_nXZ  /= divValue;
        m_nYX  /= divValue;
        m_nYY  /= divValue;
        m_nYZ  /= divValue;
        m_nZX  /= divValue;
        m_nZY  /= divValue;
        m_nZZ  /= divValue;

    }
    else
    {
        m_nXX  = 9E30;
        m_nXY  = 9E30;
        m_nXZ  = 9E30;
        m_nYX  = 9E30;
        m_nYY  = 9E30;
        m_nYZ  = 9E30;
        m_nZX  = 9E30;
        m_nZY  = 9E30;
        m_nZZ  = 9E30;
    }

    CheckForUnderflow();

    return *this;
}

inline double CSimple3x3Matrix::det() const
{
    // Our matrix is organised as:
    //
    // XX XY XZ
    // YX YY YZ
    // ZX ZY ZZ
    //
    // The formula for The determinant of a 3x3 matrix of this form is:
    //
    // XX*YY*ZZ + XY*YZ*ZX + XZ*YX*ZY - XX*YZ*ZY - XY*YX*ZZ - XZ*YY*ZX
    //
    // from:
    //
    // http://en.wikipedia.org/wiki/Determinant#3-by-3_matrices

    return m_nXX*m_nYY*m_nZZ +
           m_nXY*m_nYZ*m_nZX +
           m_nXZ*m_nYX*m_nZY -
           m_nXX*m_nYZ*m_nZY -
           m_nXY*m_nYX*m_nZZ -
           m_nXZ*m_nYY*m_nZX;
}

inline CSimple3x3Matrix CSimple3x3Matrix::inv() const
{
    CSimple3x3Matrix retVal;

    // Our matrix is organised as:
    //
    // XX XY XZ
    // YX YY YZ
    // ZX ZY ZZ
    //
    // The formula for the inverse of a matrix using Cramer's rule is:
    //
    //     Inverse(A) = 1/Determinant(A) * Adjugate(A)
    //
    // Where
    //
    //     Adjugate(A) is The Transpose of The Cofactor matrix of A
    //
    // from:
    //
    // http://en.wikipedia.org/wiki/Cramer's_rule#Finding_inverse_matrix

    // First calculate the determinant
    double ndet = det();

    // If we have a determinant of 0 we can't get the inverse
    // Set all values of the return matrix to be invalid values
    if (isZero(ndet))
    {
        retVal.setdxx(9E30);
        retVal.setdxy(9E30);
        retVal.setdxz(9E30);
        retVal.setdyx(9E30);
        retVal.setdyy(9E30);
        retVal.setdyz(9E30);
        retVal.setdzx(9E30);
        retVal.setdzy(9E30);
        retVal.setdzz(9E30);
        return retVal;
    }

    // Calculate the inverse
    retVal.setdxx( (m_nYY*m_nZZ - m_nYZ*m_nZY) / ndet );
    retVal.setdxy( (m_nXZ*m_nZY - m_nXY*m_nZZ) / ndet );
    retVal.setdxz( (m_nXY*m_nYZ - m_nXZ*m_nYY) / ndet );
    retVal.setdyx( (m_nYZ*m_nZX - m_nYX*m_nZZ) / ndet );
    retVal.setdyy( (m_nXX*m_nZZ - m_nXZ*m_nZX) / ndet );
    retVal.setdyz( (m_nXZ*m_nYX - m_nXX*m_nYZ) / ndet );
    retVal.setdzx( (m_nYX*m_nZY - m_nYY*m_nZX) / ndet );
    retVal.setdzy( (m_nXY*m_nZX - m_nXX*m_nZY) / ndet );
    retVal.setdzz( (m_nXX*m_nYY - m_nXY*m_nYX) / ndet );

    return retVal;
}

inline CSimple3x3Matrix CSimple3x3Matrix::transpose() const
{
    CSimple3x3Matrix retVal;

    // Our matrix is organised as:
    // XX XY XZ
    // YX YY YZ
    // ZX ZY ZZ

    //It needs to be returned as:
    // XX YX ZX
    // XY YY ZY
    // XZ YZ ZZ

    retVal.setdxx( m_nXX );
    retVal.setdxy( m_nYX );
    retVal.setdxz( m_nZX );
    retVal.setdyx( m_nXY );
    retVal.setdyy( m_nYY );
    retVal.setdyz( m_nZY );
    retVal.setdzx( m_nXZ );
    retVal.setdzy( m_nYZ );
    retVal.setdzz( m_nZZ );

    return retVal;
}

#endif // HELPERS_H
